from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import uuid4

import pytest

from toolbox.capabilities.ask import AskCapability
from toolbox.capabilities.translate import TranslateCapability
from toolbox.core.models import (
    ActorContext,
    AIProfile,
    CapabilityName,
    ContextItem,
    FactCheckResult,
    InteractionContext,
    LinkDocument,
    LLMRequest,
    LLMResponse,
    MessageContext,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.workflows.fact_check import FactCheckWorkflow


def request(capability: CapabilityName, text: str | None = None) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=1, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
        text=text,
        target_message=MessageContext(
            message_id=1,
            author_id=2,
            author_name="Author",
            content="Bonjour",
            channel_id=None,
            guild_id=None,
            reply_to_message_id=None,
        ),
    )


class FakeAI:
    def __init__(self, text: str) -> None:
        self.text = text
        self.profiles: list[AIProfile] = []
        self.requests: list[LLMRequest] = []

    async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
        self.profiles.append(profile)
        self.requests.append(request)
        return LLMResponse(text=self.text)


@pytest.mark.asyncio
async def test_ask_uses_normal_profile_and_selected_message() -> None:
    ai = FakeAI("It means hello.")

    result = await AskCapability(ai).execute(request(CapabilityName.ASK, "what does this mean?"))

    assert isinstance(result, TextResult)
    assert ai.profiles == [AIProfile.NORMAL]
    assert "Bonjour" in ai.requests[0].input


@pytest.mark.asyncio
async def test_translate_uses_normal_profile_and_strips_response_whitespace() -> None:
    ai = FakeAI("Hello")

    translation_request = replace(
        request(CapabilityName.TRANSLATE, "Bonjour"),
        options={"source_language": "French"},
    )
    result = await TranslateCapability(ai).execute(translation_request)

    assert isinstance(result, TextResult)
    assert ai.profiles == [AIProfile.NORMAL]
    assert "SOURCE LANGUAGE: French" in ai.requests[0].input
    assert "English" in ai.requests[0].input


@pytest.mark.asyncio
async def test_translate_rejects_an_echoed_source_instead_of_showing_it_as_translation() -> None:
    ai = FakeAI("  Weley Khu jagara wi  ")

    result = await TranslateCapability(ai).execute(
        request(CapabilityName.TRANSLATE, "Weley Khu jagara wi")
    )

    assert result.__class__.__name__ == "ErrorResult"
    assert "couldn't confidently translate" in result.message  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_ask_loads_explicit_context_basket_before_prompting() -> None:
    class Context:
        async def add(self, item: ContextItem) -> None:
            del item

        async def list(self, owner_id: int) -> Sequence[ContextItem]:
            assert owner_id == 1
            return (
                ContextItem(
                    item_id=uuid4(),
                    owner_id=owner_id,
                    label="selected context",
                    text="Only this context was explicitly selected.",
                ),
            )

        async def clear(self, owner_id: int) -> None:
            del owner_id

    ai = FakeAI("answer")
    result = await AskCapability(ai, context_store=Context()).execute(
        request(CapabilityName.ASK, "use my context")
    )

    assert isinstance(result, TextResult)
    assert "Only this context" in ai.requests[0].input


@pytest.mark.asyncio
async def test_fact_check_workflow_searches_before_synthesizing() -> None:
    from toolbox.core.models import SearchHit, SearchPage, SearchRequest, Verdict

    class FakeSearch:
        def __init__(self) -> None:
            self.called = False

        async def search(self, request: SearchRequest) -> SearchPage:
            self.called = True
            return SearchPage(
                query=request.query,
                kind=request.kind,
                hits=(
                    SearchHit(
                        title="Evidence",
                        url="https://example.com",
                        snippet="Search evidence",
                    ),
                ),
            )

    class FakeFetcher:
        async def fetch(self, url: str) -> LinkDocument:
            assert url == "https://example.com"
            return LinkDocument(
                url=url,
                title="Evidence",
                text="Retrieved truth from the source page.",
            )

    class StructuredAI(FakeAI):
        async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
            self.profiles.append(profile)
            self.requests.append(request)
            return LLMResponse(
                text='{"verdict":"true","explanation":"The source supports it."}',
                structured={"verdict": "true", "explanation": "The source supports it."},
            )

    search = FakeSearch()
    ai = StructuredAI("unused")
    result = await FactCheckWorkflow(search=search, ai=ai, fetcher=FakeFetcher()).execute(
        request(CapabilityName.FACT_CHECK, "The claim")
    )

    assert isinstance(result, FactCheckResult)
    assert result.verdict is Verdict.TRUE
    assert search.called is True
    assert ai.profiles == [AIProfile.RESEARCH]
    assert "https://example.com" in ai.requests[0].input
    assert "Retrieved truth from the source page" in ai.requests[0].input
