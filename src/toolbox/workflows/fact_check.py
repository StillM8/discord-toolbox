"""Explicit fact-check orchestration: search evidence, then synthesize."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from toolbox.core.actions import share_action
from toolbox.core.contracts import AIService, LinkFetcher, WebSearchProvider
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AIProfile,
    ErrorResult,
    FactCheckResult,
    LLMRequest,
    SearchHit,
    SearchKind,
    SearchRequest,
    SourceRef,
    ToolRequest,
    Verdict,
)


class FactCheckWorkflow:
    """Coordinate raw evidence retrieval and structured AI analysis."""

    def __init__(
        self,
        *,
        search: WebSearchProvider,
        ai: AIService,
        fetcher: LinkFetcher | None = None,
        max_sources: int = 5,
        max_source_chars: int = 3_500,
        max_evidence_chars: int = 14_000,
    ) -> None:
        self._search = search
        self._ai = ai
        self._fetcher = fetcher
        self._max_sources = max(1, min(max_sources, 10))
        self._max_source_chars = max(500, min(max_source_chars, 6_000))
        self._max_evidence_chars = max(2_000, min(max_evidence_chars, 20_000))

    async def execute(self, request: ToolRequest) -> FactCheckResult | ErrorResult:
        claim = request.text or (
            request.target_message.content if request.target_message else ""
        )
        claim = claim.strip()
        if not claim or len(claim) > 2_000:
            return self._error("invalid_request", "Give me a claim to fact-check.")
        try:
            page = await self._search.search(
                SearchRequest(query=claim, kind=SearchKind.WEB, limit=self._max_sources)
            )
            sources = tuple(
                SourceRef(title=hit.title, url=hit.url, source_name=hit.source_name)
                for hit in page.hits[: self._max_sources]
            )
            if not sources:
                return self._error(
                    "no_evidence",
                    "Search did not return verifiable sources for that claim.",
                    retryable=True,
                )
            evidence = await self._evidence(page.hits[: self._max_sources], sources)
            response = await self._ai.generate(
                AIProfile.RESEARCH,
                LLMRequest(
                    system=(
                        "Evaluate the claim only against the retrieved source text and search "
                        "snippets supplied below. Do not rely on unsupported prior knowledge. "
                        "If the evidence is insufficient or conflicting, use unverified or mixed. "
                        "Return JSON with verdict, explanation. Verdict must be one of: "
                        "true, mostly_true, mixed, mostly_false, false, unverified."
                    ),
                    input=f"CLAIM:\n{claim}\n\nSOURCES:\n{evidence}",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "verdict": {"type": "string"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["verdict", "explanation"],
                        "additionalProperties": False,
                    },
                    max_output_tokens=1_000,
                ),
            )
            structured = cast(object, response.structured)
            raw_data: object
            if isinstance(structured, dict):
                raw_data = cast(object, structured)
            else:
                raw_data = cast(object, json.loads(response.text))
            data = cast(Mapping[str, object], raw_data)
            verdict = Verdict(str(data["verdict"]))
            explanation = str(data["explanation"])
        except (ToolboxError, InvalidRequest) as error:
            return self._error(error.code, error.user_message, error.retryable)
        except (KeyError, ValueError, json.JSONDecodeError):
            return self._error(
                "invalid_provider_output",
                "The fact-check result could not be validated.",
            )
        return FactCheckResult(
            claim=claim,
            verdict=verdict,
            explanation=explanation,
            sources=sources,
            actions=(share_action(),),
        )

    async def _evidence(self, hits: tuple[SearchHit, ...], sources: tuple[SourceRef, ...]) -> str:
        """Fetch bounded source text so the verdict is grounded in online evidence."""

        parts: list[str] = []
        remaining = self._max_evidence_chars
        for index, source in enumerate(sources):
            if remaining <= 0:
                break
            hit = hits[index]
            snippet = hit.snippet
            source_parts = [
                f"SOURCE {index + 1}",
                f"TITLE: {source.title}",
                f"URL: {source.url}",
            ]
            if isinstance(snippet, str) and snippet.strip():
                source_parts.append(f"SEARCH SNIPPET: {snippet[:1_000]}")
            if self._fetcher is not None:
                try:
                    document = await self._fetcher.fetch(source.url)
                except ToolboxError:
                    document = None
                if document is not None and document.text.strip():
                    source_parts.append(
                        "RETRIEVED SOURCE TEXT:\n"
                        + " ".join(document.text.split())[: self._max_source_chars]
                    )
            block = "\n".join(source_parts)
            bounded = block[:remaining]
            parts.append(bounded)
            remaining -= len(bounded)
        return "\n\n".join(parts) or "No sources were returned."

    @staticmethod
    def _error(code: str, message: str, retryable: bool = False) -> ErrorResult:
        return ErrorResult(code=code, message=message, retryable=retryable)
