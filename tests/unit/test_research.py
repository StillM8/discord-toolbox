from __future__ import annotations

from uuid import uuid4

import pytest

from toolbox.capabilities.explain import WhatIsThisCapability
from toolbox.core.models import (
    ActorContext,
    AIProfile,
    CapabilityName,
    InteractionContext,
    LLMRequest,
    LLMResponse,
    SearchHit,
    SearchPage,
    SearchRequest,
    SourceRef,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.workflows.research import ResearchWorkflow


def request(capability: CapabilityName, text: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        text=text,
    )


@pytest.mark.asyncio
async def test_research_workflow_searches_before_ai_and_keeps_sources() -> None:
    class Search:
        async def search(self, request: SearchRequest) -> SearchPage:
            assert request.query == "why"
            return SearchPage(
                query="why",
                kind=request.kind,
                hits=(SearchHit(title="Evidence", url="https://example.com", snippet="fact"),),
            )

    class AI:
        async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
            assert profile is AIProfile.RESEARCH
            assert "Evidence" in request.input
            return LLMResponse(text="A sourced answer.")

    result = await ResearchWorkflow(search=Search(), ai=AI()).execute(
        request(CapabilityName.RESEARCH, "why")
    )

    assert isinstance(result, TextResult)
    assert result.text == "A sourced answer."
    assert result.sources == (SourceRef("Evidence", "https://example.com", None),)


@pytest.mark.asyncio
async def test_what_is_this_uses_normal_ai_profile() -> None:
    class AI:
        async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
            assert profile is AIProfile.NORMAL
            assert "CONTENT" in request.input
            return LLMResponse(text="An explanation.")

    result = await WhatIsThisCapability(AI()).execute(
        request(CapabilityName.WHAT_IS_THIS, "quantum tunneling")
    )

    assert isinstance(result, TextResult)
    assert result.text == "An explanation."
