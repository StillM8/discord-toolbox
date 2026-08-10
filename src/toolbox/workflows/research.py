"""Bounded search-and-synthesis workflow with explicit source references."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import AIService, WebSearchProvider
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AIProfile,
    ErrorResult,
    LLMRequest,
    SearchKind,
    SearchRequest,
    SourceRef,
    TextResult,
    ToolRequest,
    ToolResult,
)


class ResearchWorkflow:
    """Retrieve bounded web evidence, then ask AI to synthesize it."""

    def __init__(
        self,
        *,
        search: WebSearchProvider,
        ai: AIService,
        max_sources: int = 5,
    ) -> None:
        self._search = search
        self._ai = ai
        self._max_sources = max(1, min(max_sources, 10))

    async def execute(self, request: ToolRequest) -> ToolResult:
        query = (request.text or request.options.get("query", "")).strip()
        if not query or len(query) > 2_000:
            error = InvalidRequest
            return ErrorResult(code=error.code, message="Give me a research question.")
        try:
            page = await self._search.search(
                SearchRequest(query=query, kind=SearchKind.WEB, limit=self._max_sources)
            )
            sources = tuple(
                SourceRef(title=hit.title, url=hit.url, source_name=hit.source_name)
                for hit in page.hits[: self._max_sources]
            )
            evidence = "\n\n".join(
                f"SOURCE {index}: {source.title}\nURL: {source.url}\n"
                f"SUMMARY: {page.hits[index - 1].snippet or 'No snippet provided.'}"
                for index, source in enumerate(sources, start=1)
            ) or "No search sources were returned."
            response = await self._ai.generate(
                AIProfile.RESEARCH,
                LLMRequest(
                    system=(
                        "Answer the research question using only the supplied source metadata "
                        "and snippets. Be concise, distinguish evidence from inference, and "
                        "say when the sources are insufficient. Do not invent citations."
                    ),
                    input=f"QUESTION:\n{query}\n\nEVIDENCE:\n{evidence}",
                    max_output_tokens=2_000,
                ),
            )
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return TextResult(
            title=f"Research: {query}",
            text=response.text,
            input_text=query,
            sources=sources,
            actions=(share_action(),),
        )
