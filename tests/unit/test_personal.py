from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from toolbox.capabilities.personal import (
    ContextAddCapability,
    ContextListCapability,
    SaveCapability,
    SavedDeleteCapability,
    SavedSearchCapability,
    SavedSendDMCapability,
    ShareCapability,
)
from toolbox.core.models import (
    ActionKind,
    ActorContext,
    AssetRef,
    AttachmentRef,
    CapabilityName,
    ContextItem,
    ErrorResult,
    InteractionContext,
    InteractionSession,
    SavedItem,
    SavedItemKind,
    TextResult,
    ToolRequest,
    UserContext,
    Visibility,
)
from toolbox.core.result_codec import ResultCodec


def request(
    capability: CapabilityName,
    text: str | None = None,
    *,
    public: bool = False,
) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(
            guild_id=None,
            channel_id=None,
            surface="dm",
            public_allowed=public,
        ),
        text=text,
    )


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_context_add_uses_only_explicit_input() -> None:
    class Store:
        def __init__(self) -> None:
            self.item: ContextItem | None = None

        async def add(self, item: ContextItem) -> None:
            self.item = item

        async def list(self, owner_id: int) -> Sequence[ContextItem]:
            return (self.item,) if self.item is not None else ()

        async def clear(self, owner_id: int) -> None:
            self.item = None

    store = Store()
    result = await ContextAddCapability(store).execute(
        request(CapabilityName.CONTEXT_ADD, "selected")
    )

    assert isinstance(result, TextResult)
    assert store.item is not None
    assert store.item.text == "selected"


@pytest.mark.asyncio
async def test_context_list_describes_only_the_owner_basket() -> None:
    item = ContextItem(
        item_id=uuid4(),
        owner_id=42,
        label="selected message",
        text="the selected text",
    )

    class Store:
        async def add(self, item: ContextItem) -> None:
            del item

        async def list(self, owner_id: int) -> Sequence[ContextItem]:
            assert owner_id == 42
            return (item,)

        async def clear(self, owner_id: int) -> None:
            del owner_id

    result = await ContextListCapability(Store()).execute(request(CapabilityName.CONTEXT_LIST))

    assert isinstance(result, TextResult)
    assert "the selected text" in result.text


@pytest.mark.asyncio
async def test_save_capability_persists_owner_scoped_item() -> None:
    class Repository:
        def __init__(self) -> None:
            self.item: SavedItem | None = None

        async def save(self, item: SavedItem) -> None:
            self.item = item

        async def search(self, owner_id: int, query: str) -> Sequence[SavedItem]:
            return (self.item,) if self.item is not None else ()

        async def get(self, owner_id: int, item_id: UUID) -> SavedItem | None:
            if (
                self.item is not None
                and self.item.owner_id == owner_id
                and self.item.item_id == item_id
            ):
                return self.item
            return None

        async def delete(self, owner_id: int, item_id: UUID) -> None:
            self.item = None

    repository = Repository()
    result = await SaveCapability(repository, FakeClock()).execute(
        request(CapabilityName.SAVE, "remember this")
    )

    assert isinstance(result, TextResult)
    assert repository.item is not None
    assert repository.item.owner_id == 42


@pytest.mark.asyncio
async def test_save_supports_tags_attachments_and_optional_dm_delivery() -> None:
    class Repository:
        def __init__(self) -> None:
            self.item: SavedItem | None = None

        async def save(self, item: SavedItem) -> None:
            self.item = item

        async def search(self, owner_id: int, query: str) -> Sequence[SavedItem]:
            return ()

        async def get(self, owner_id: int, item_id: UUID) -> SavedItem | None:
            return self.item

        async def delete(self, owner_id: int, item_id: UUID) -> None:
            return None

    class Ingestor:
        async def ingest(self, attachment: object, owner_id: int) -> AssetRef:
            return AssetRef(
                asset_id=uuid4(),
                mime_type="image/png",
                size=123,
                owner_id=owner_id,
            )

    class Delivery:
        def __init__(self) -> None:
            self.item: SavedItem | None = None

        async def deliver(self, item: SavedItem) -> None:
            self.item = item

    repository = Repository()
    delivery = Delivery()
    result = await SaveCapability(
        repository,
        FakeClock(),
        ingestor=Ingestor(),
        delivery=delivery,
    ).execute(
        replace(
            request(CapabilityName.SAVE, "a useful image"),
            attachments=(
                # The application only needs normalized attachment metadata here.
                # The concrete Discord adapter is tested separately.
                AttachmentRef(
                    attachment_id="1",
                    source_url="https://cdn.example/image.png",
                    filename="image.png",
                    declared_content_type="image/png",
                    declared_size=123,
                ),
            ),
            options={
                "title": "Read later",
                "tags": "read, ideas, read",
                "send_to_dm": "true",
            },
        )
    )

    assert isinstance(result, TextResult)
    assert "sent a copy" in result.text
    assert repository.item is not None
    assert repository.item.title == "Read later"
    assert repository.item.tags == ("read", "ideas")
    assert repository.item.asset_mime_type == "image/png"
    assert repository.item.asset_size == 123
    assert delivery.item == repository.item


@pytest.mark.asyncio
async def test_saved_send_dm_reauthorizes_owner_and_consumes_session() -> None:
    item = SavedItem(
        item_id=uuid4(),
        owner_id=42,
        kind=SavedItemKind.TEXT,
        title="A note",
        text="remember this",
        source_url=None,
        asset_id=None,
        created_at=datetime.now(UTC),
    )
    session_id = uuid4()

    class Repository:
        async def save(self, item: SavedItem) -> None:
            del item

        async def search(self, owner_id: int, query: str) -> Sequence[SavedItem]:
            return ()

        async def get(self, owner_id: int, item_id: UUID) -> SavedItem | None:
            return item if owner_id == item.owner_id and item_id == item.item_id else None

        async def delete(self, owner_id: int, item_id: UUID) -> None:
            del owner_id, item_id

    class Sessions:
        def __init__(self) -> None:
            self.deleted = False

        async def create(self, session: InteractionSession) -> None:
            del session

        async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
            return InteractionSession(
                session_id=session_id,
                owner_id=owner_id,
                action=ActionKind.SEND_DM,
                target_id=item.item_id,
                payload={"item_id": str(item.item_id)},
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

        async def delete(self, owner_id: int, session_id: UUID) -> None:
            del owner_id, session_id
            self.deleted = True

    class Delivery:
        def __init__(self) -> None:
            self.delivered: SavedItem | None = None

        async def deliver(self, item: SavedItem) -> None:
            self.delivered = item

    sessions = Sessions()
    delivery = Delivery()
    result = await SavedSendDMCapability(Repository(), sessions, delivery).execute(
        replace(request(CapabilityName.SAVED_SEND_DM), session_id=session_id)
    )

    assert isinstance(result, TextResult)
    assert delivery.delivered == item
    assert sessions.deleted is True


@pytest.mark.asyncio
async def test_share_reauthorizes_session_owner_and_visibility() -> None:
    class Sessions:
        async def create(self, session: InteractionSession) -> None:
            return None

        async def get(self, owner_id: int, session_id: UUID) -> InteractionSession:
            return InteractionSession(
                session_id=session_id,
                owner_id=owner_id,
                action=ActionKind.SHARE,
                target_id=None,
                payload=ResultCodec().encode(
                    TextResult(text="private", input_text="the original request")
                ),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

        async def delete(self, owner_id: int, session_id: UUID) -> None:
            return None

    session_id = uuid4()
    request_value = request(CapabilityName.SHARE, public=True)
    request_value = replace(request_value, session_id=session_id)
    result = await ShareCapability(Sessions(), ResultCodec()).execute(request_value)

    assert isinstance(result, TextResult)
    assert result.visibility is Visibility.PUBLIC
    assert result.input_text == "the original request"


@pytest.mark.asyncio
async def test_share_explains_external_app_public_restriction() -> None:
    class Sessions:
        async def create(self, session: InteractionSession) -> None:
            return None

        async def get(self, owner_id: int, session_id: UUID) -> InteractionSession:
            del owner_id
            return InteractionSession(
                session_id=session_id,
                owner_id=42,
                action=ActionKind.SHARE,
                target_id=None,
                payload=ResultCodec().encode(TextResult(text="private")),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

        async def delete(self, owner_id: int, session_id: UUID) -> None:
            return None

    session_id = uuid4()
    result = await ShareCapability(Sessions(), ResultCodec()).execute(
        replace(request(CapabilityName.SHARE), session_id=session_id)
    )

    assert isinstance(result, ErrorResult)
    assert result.code == "public_response_forbidden"
    assert "Use External Apps" in result.message


@pytest.mark.asyncio
async def test_saved_search_and_delete_remain_owner_scoped() -> None:
    class Saved:
        def __init__(self) -> None:
            self.items: list[SavedItem] = []

        async def save(self, item: SavedItem) -> None:
            self.items.append(item)

        async def search(self, owner_id: int, query: str) -> Sequence[SavedItem]:
            return tuple(
                item
                for item in self.items
                if item.owner_id == owner_id and query.lower() in (item.text or "").lower()
            )

        async def get(self, owner_id: int, item_id: UUID) -> SavedItem | None:
            return next(
                (
                    item
                    for item in self.items
                    if item.owner_id == owner_id and item.item_id == item_id
                ),
                None,
            )

        async def delete(self, owner_id: int, item_id: UUID) -> None:
            self.items = [
                item
                for item in self.items
                if not (item.owner_id == owner_id and item.item_id == item_id)
            ]

    repository = Saved()
    item = SavedItem(
        item_id=uuid4(),
        owner_id=42,
        kind=SavedItemKind.TEXT,
        title="Note",
        text="remember this",
        source_url=None,
        asset_id=None,
        created_at=datetime.now(UTC),
    )
    await repository.save(item)

    found = await SavedSearchCapability(repository).execute(
        request(CapabilityName.SAVED_SEARCH, "remember")
    )
    assert isinstance(found, TextResult)
    assert str(item.item_id) in found.text

    deleted = await SavedDeleteCapability(repository).execute(
        replace(
            request(CapabilityName.SAVED_DELETE),
            options={"item_id": str(item.item_id)},
        )
    )
    assert isinstance(deleted, TextResult)
    assert not repository.items
