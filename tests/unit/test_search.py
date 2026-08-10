from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from toolbox.capabilities.search import SearchCapability
from toolbox.capabilities.search_expand import SearchExpandCapability
from toolbox.core.errors import FeatureDisabled, ProviderTimeout, ProviderUnavailable
from toolbox.core.models import (
    ActionKind,
    ActorContext,
    CapabilityName,
    InteractionContext,
    InteractionSession,
    LinkDocument,
    MessageContext,
    SearchHit,
    SearchKind,
    SearchPage,
    SearchRequest,
    SearchResults,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.providers.search.brave import BraveSearchProvider
from toolbox.providers.search.giphy import GiphySearchProvider
from toolbox.providers.search.searxng import SearXNGSearchProvider
from toolbox.providers.search.unavailable import UnavailableGifSearchProvider


def request(
    capability: CapabilityName,
    text: str | None,
    *,
    target_message: MessageContext | None = None,
) -> ToolRequest:
    from uuid import uuid4

    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=1, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
        text=text,
        target_message=target_message,
    )


@pytest.mark.asyncio
async def test_brave_provider_normalizes_web_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/web/search")
        assert request.headers["X-Subscription-Token"] == "secret"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.com",
                            "description": "A result",
                        }
                    ]
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        page = await BraveSearchProvider(client, api_key="secret").search(
            SearchRequest(query="example", kind=SearchKind.WEB)
        )
    finally:
        await client.aclose()

    assert page.hits[0].title == "Example"
    assert page.hits[0].url == "https://example.com"


@pytest.mark.asyncio
async def test_giphy_provider_normalizes_gif_results_without_leaking_api_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/gifs/search"
        assert request.url.params["api_key"] == "secret"
        assert request.url.params["rating"] == "g"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "title": "A reaction",
                        "url": "https://giphy.com/gifs/example",
                        "images": {
                            "original": {"url": "https://media.example/original.gif"},
                            "fixed_width_small": {"url": "https://media.example/preview.gif"},
                        },
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        page = await GiphySearchProvider(client, api_key="secret").search(
            SearchRequest(query="confused", kind=SearchKind.GIF)
        )
    finally:
        await client.aclose()

    assert page.kind is SearchKind.GIF
    assert page.hits[0].title == "A reaction"
    assert page.hits[0].url == "https://giphy.com/gifs/example"
    assert page.hits[0].thumbnail_url == "https://media.example/preview.gif"


@pytest.mark.asyncio
async def test_disabled_gif_provider_is_explicit() -> None:
    with pytest.raises(FeatureDisabled):
        await UnavailableGifSearchProvider().search(
            SearchRequest(query="confused", kind=SearchKind.GIF)
        )


@pytest.mark.asyncio
async def test_search_capability_returns_application_results() -> None:
    class FakeProvider:
        async def search(self, request: SearchRequest):
            from toolbox.core.models import SearchHit, SearchPage

            return SearchPage(
                query=request.query,
                kind=request.kind,
                hits=(SearchHit(title="Result", url="https://example.com"),),
            )

    result = await SearchCapability(FakeProvider()).execute(
        request(CapabilityName.SEARCH_WEB, "toolbox")
    )

    assert isinstance(result, SearchResults)
    assert result.items[0].title == "Result"


@pytest.mark.asyncio
async def test_search_uses_selected_message_for_toolbox_search() -> None:
    class FakeProvider:
        async def search(self, request: SearchRequest) -> SearchPage:
            assert request.query == "why do cats chirp"
            return SearchPage(
                query=request.query,
                kind=request.kind,
                hits=(SearchHit(title="Cats", url="https://example.com/cats"),),
            )

    result = await SearchCapability(FakeProvider()).execute(
        request(
            CapabilityName.SEARCH_WEB,
            None,
            target_message=MessageContext(
                message_id=5,
                author_id=6,
                author_name="Author",
                content="why do cats chirp",
                channel_id=None,
                guild_id=None,
                reply_to_message_id=None,
            ),
        )
    )

    assert isinstance(result, SearchResults)
    assert result.items[0].title == "Cats"


@pytest.mark.asyncio
async def test_brave_timeout_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderTimeout):
            await BraveSearchProvider(client, api_key="secret").search(
                SearchRequest(query="example")
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "category"),
    [
        (SearchKind.WEB, "general"),
        (SearchKind.IMAGES, "images"),
        (SearchKind.NEWS, "news"),
        (SearchKind.VIDEO, "videos"),
    ],
)
async def test_searxng_provider_maps_categories_and_results(
    kind: SearchKind,
    category: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["format"] == "json"
        assert request.url.params["categories"] == category
        assert request.url.params["pageno"] == "1"
        assert request.url.params["safesearch"] == "1"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "SearX result",
                        "url": "https://example.com/result",
                        "content": "A normalized result",
                        "engine": "example",
                        "thumbnail": "https://example.com/thumb.jpg",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        page = await SearXNGSearchProvider(client).search(
            SearchRequest(query="toolbox", kind=kind, safe_search="moderate")
        )
    finally:
        await client.aclose()

    assert page.kind is kind
    assert page.hits[0] == SearchHit(
        title="SearX result",
        url="https://example.com/result",
        snippet="A normalized result",
        source_name="example",
        thumbnail_url="https://example.com/thumb.jpg",
    )


@pytest.mark.asyncio
async def test_searxng_provider_paginates_with_server_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["pageno"] == "2"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "One", "url": "https://example.com/one"},
                    {"title": "Two", "url": "https://example.com/two"},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        page = await SearXNGSearchProvider(client).search(
            SearchRequest(query="toolbox", cursor="2", limit=2)
        )
    finally:
        await client.aclose()

    assert page.next_cursor == "3"


@pytest.mark.asyncio
async def test_searxng_provider_normalizes_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderUnavailable):
            await SearXNGSearchProvider(client).search(SearchRequest(query="toolbox"))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_search_paginates_one_result_at_a_time_before_fetching_next_provider_page() -> None:
    class Sessions:
        def __init__(self) -> None:
            self.items: dict[UUID, InteractionSession] = {}
            self.deleted: list[UUID] = []

        async def create(self, session: InteractionSession) -> None:
            self.items[session.session_id] = session

        async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
            session = self.items.get(session_id)
            return session if session is not None and session.owner_id == owner_id else None

        async def delete(self, owner_id: int, session_id: UUID) -> None:
            del owner_id
            self.deleted.append(session_id)
            self.items.pop(session_id, None)

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    class Provider:
        def __init__(self) -> None:
            self.cursors: list[str | None] = []

        async def search(self, request: SearchRequest) -> SearchPage:
            self.cursors.append(request.cursor)
            if request.cursor is None:
                hits = (
                    SearchHit(title="One", url="https://example.com/one"),
                    SearchHit(title="Two", url="https://example.com/two"),
                )
                next_cursor = "page-2"
            else:
                hits = (SearchHit(title="Three", url="https://example.com/three"),)
                next_cursor = None
            return SearchPage(
                query=request.query,
                kind=request.kind,
                hits=hits,
                next_cursor=next_cursor,
            )

    sessions = Sessions()
    provider = Provider()
    capability = SearchCapability(provider, sessions=sessions, clock=Clock())
    first = await capability.execute(request(CapabilityName.SEARCH_WEB, "toolbox"))

    assert isinstance(first, SearchResults)
    assert len(first.items) == 1
    assert first.items[0].title == "One"
    next_action = next(action for action in first.actions if action.kind is ActionKind.NEXT_PAGE)
    assert next_action.session_id is not None
    second = await capability.execute(
        replace(
            request(CapabilityName.SEARCH_WEB, ""),
            session_id=next_action.session_id,
        )
    )

    assert isinstance(second, SearchResults)
    assert len(second.items) == 1
    assert second.items[0].title == "Two"
    assert provider.cursors == [None]
    next_action = next(action for action in second.actions if action.kind is ActionKind.NEXT_PAGE)
    assert next_action.session_id is not None
    third = await capability.execute(
        replace(
            request(CapabilityName.SEARCH_WEB, ""),
            session_id=next_action.session_id,
        )
    )

    assert isinstance(third, SearchResults)
    assert len(third.items) == 1
    assert third.items[0].title == "Three"
    assert not any(action.kind is ActionKind.NEXT_PAGE for action in third.actions)
    assert provider.cursors == [None, "page-2"]

    back_action = next(
        action for action in third.actions if action.kind is ActionKind.PREVIOUS_PAGE
    )
    second_again = await capability.execute(
        replace(
            request(CapabilityName.SEARCH_WEB, None),
            session_id=back_action.session_id,
        )
    )
    assert isinstance(second_again, SearchResults)
    assert second_again.items[0].title == "Two"
    assert any(action.kind is ActionKind.PREVIOUS_PAGE for action in second_again.actions)

    back_action = next(
        action for action in second_again.actions if action.kind is ActionKind.PREVIOUS_PAGE
    )
    first_again = await capability.execute(
        replace(
            request(CapabilityName.SEARCH_WEB, None),
            session_id=back_action.session_id,
        )
    )
    assert isinstance(first_again, SearchResults)
    assert first_again.items[0].title == "One"
    assert not any(action.kind is ActionKind.PREVIOUS_PAGE for action in first_again.actions)
    assert provider.cursors == [None, "page-2"]


@pytest.mark.asyncio
async def test_image_search_returns_one_image_and_next_action() -> None:
    class Sessions:
        def __init__(self) -> None:
            self.items: dict[UUID, InteractionSession] = {}

        async def create(self, session: InteractionSession) -> None:
            self.items[session.session_id] = session

        async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
            session = self.items.get(session_id)
            return session if session is not None and session.owner_id == owner_id else None

        async def delete(self, owner_id: int, session_id: UUID) -> None:
            del owner_id
            self.items.pop(session_id, None)

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    class Provider:
        async def search(self, request: SearchRequest) -> SearchPage:
            return SearchPage(
                query=request.query,
                kind=request.kind,
                hits=(
                    SearchHit(
                        title="One image",
                        url="https://example.com/one",
                        thumbnail_url="https://example.com/one.jpg",
                    ),
                    SearchHit(
                        title="Two image",
                        url="https://example.com/two",
                        thumbnail_url="https://example.com/two.jpg",
                    ),
                ),
            )

    result = await SearchCapability(
        Provider(),
        sessions=Sessions(),
        clock=Clock(),
    ).execute(request(CapabilityName.SEARCH_IMAGES, "cats"))

    assert isinstance(result, SearchResults)
    assert len(result.items) == 1
    assert result.items[0].thumbnail_url == "https://example.com/one.jpg"
    assert not any(action.kind is ActionKind.EXPAND for action in result.actions)
    assert any(action.kind is ActionKind.NEXT_PAGE for action in result.actions)


@pytest.mark.asyncio
async def test_search_expand_fetches_a_bounded_source_preview() -> None:
    class Sessions:
        def __init__(self) -> None:
            self.items: dict[UUID, InteractionSession] = {}

        async def create(self, session: InteractionSession) -> None:
            self.items[session.session_id] = session

        async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
            session = self.items.get(session_id)
            return session if session is not None and session.owner_id == owner_id else None

        async def delete(self, owner_id: int, session_id: UUID) -> None:
            del owner_id
            self.items.pop(session_id, None)

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    class Provider:
        async def search(self, request: SearchRequest) -> SearchPage:
            return SearchPage(
                query=request.query,
                kind=request.kind,
                hits=(
                    SearchHit(
                        title="Result",
                        url="https://example.com/result",
                        snippet="A short result preview.",
                    ),
                ),
            )

    sessions = Sessions()
    search_result = await SearchCapability(
        Provider(),
        sessions=sessions,
        clock=Clock(),
    ).execute(request(CapabilityName.SEARCH_WEB, "toolbox"))
    assert isinstance(search_result, SearchResults)
    expand = next(action for action in search_result.actions if action.kind is ActionKind.EXPAND)

    class Fetcher:
        async def fetch(self, url: str) -> LinkDocument:
            assert url == "https://example.com/result"
            return LinkDocument(
                url=url,
                title="Expanded result",
                text="word " * 2_000,
            )

    expanded = await SearchExpandCapability(fetcher=Fetcher(), sessions=sessions).execute(
        replace(
            request(CapabilityName.SEARCH_EXPAND, None),
            session_id=expand.session_id,
        )
    )

    assert isinstance(expanded, TextResult)
    assert expanded.title == "Expanded result"
    assert len(expanded.text) == 1_800
    assert expanded.sources[0].url == "https://example.com/result"


@pytest.mark.asyncio
async def test_search_pagination_preserves_news_mode() -> None:
    class Sessions:
        def __init__(self) -> None:
            self.items: dict[UUID, InteractionSession] = {}

        async def create(self, session: InteractionSession) -> None:
            self.items[session.session_id] = session

        async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
            session = self.items.get(session_id)
            return session if session is not None and session.owner_id == owner_id else None

        async def delete(self, owner_id: int, session_id: UUID) -> None:
            del owner_id
            self.items.pop(session_id, None)

    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    class Provider:
        def __init__(self) -> None:
            self.kinds: list[SearchKind] = []

        async def search(self, request: SearchRequest) -> SearchPage:
            self.kinds.append(request.kind)
            return SearchPage(
                query=request.query,
                kind=request.kind,
                hits=(SearchHit(title="News", url="https://example.com/news"),),
                next_cursor="5" if request.cursor is None else None,
            )

    sessions = Sessions()
    provider = Provider()
    capability = SearchCapability(provider, sessions=sessions, clock=Clock())
    first = await capability.execute(
        ToolRequest(
            request_id=uuid4(),
            capability=CapabilityName.SEARCH_WEB,
            actor=ActorContext(user=UserContext(user_id=1, display_name="Tester")),
            interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
            text="topic",
            options={"kind": SearchKind.NEWS.value},
        )
    )
    assert isinstance(first, SearchResults)
    next_action = next(action for action in first.actions if action.kind is ActionKind.NEXT_PAGE)
    await capability.execute(
        ToolRequest(
            request_id=uuid4(),
            capability=CapabilityName.SEARCH_WEB,
            actor=ActorContext(user=UserContext(user_id=1, display_name="Tester")),
            interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
            session_id=next_action.session_id,
        )
    )
    assert provider.kinds == [SearchKind.NEWS, SearchKind.NEWS]
