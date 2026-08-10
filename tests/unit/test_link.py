from __future__ import annotations

import httpx
import pytest

from toolbox.core.models import (
    ActorContext,
    AIProfile,
    CapabilityName,
    InteractionContext,
    LLMRequest,
    LLMResponse,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.infrastructure.url_policy import RemoteUrlPolicy
from toolbox.providers.links import http as link_http
from toolbox.providers.links.http import HttpLinkFetcher
from toolbox.workflows.link_summary import LinkSummaryWorkflow


def request(text: str) -> ToolRequest:
    from uuid import uuid4

    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.LINK_SUMMARIZE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        text=text,
    )


@pytest.mark.asyncio
async def test_link_workflow_fetches_bounded_text_before_ai() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert str(http_request.url) == "https://example.com/article"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=(
                b"<html><title>Article</title><script>secret()</script>"
                b"<p>Hello world.</p></html>"
            ),
        )

    class AI:
        async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
            assert profile is AIProfile.NORMAL
            assert "secret" not in request.input
            assert "Hello world." in request.input
            return LLMResponse(text="A short summary.")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    try:
        workflow = LinkSummaryWorkflow(
            fetcher=HttpLinkFetcher(
                client,
                url_policy=RemoteUrlPolicy(resolver=lambda host, port: ("93.184.216.34",)),
            ),
            ai=AI(),
        )
        result = await workflow.execute(request("https://example.com/article"))
    finally:
        await client.aclose()

    assert isinstance(result, TextResult)
    assert "A short summary." in result.text
    assert "https://example.com/article" in result.text


@pytest.mark.asyncio
async def test_link_workflow_rejects_missing_url_without_fetching() -> None:
    class Fetcher:
        async def fetch(self, url: str):
            raise AssertionError(url)

    class AI:
        async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
            raise AssertionError((profile, request))

    result = await LinkSummaryWorkflow(fetcher=Fetcher(), ai=AI()).execute(request("hello"))

    assert result.code == "invalid_request"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_link_fetcher_falls_back_when_article_extractor_rejects_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_for_malformed_html(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValueError("malformed document")

    monkeypatch.setattr(link_http.trafilatura, "extract", raise_for_malformed_html)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<html><title>Fallback title</title><p>Fallback text.</p></html>",
            )
        ),
        follow_redirects=False,
    )
    try:
        document = await HttpLinkFetcher(
            client,
            url_policy=RemoteUrlPolicy(resolver=lambda host, port: ("93.184.216.34",)),
        ).fetch("https://example.com/article")
    finally:
        await client.aclose()

    assert document.title == "Fallback title"
    assert document.text == "Fallback text."
