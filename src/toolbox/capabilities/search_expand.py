"""Bounded expansion of one search result through the safe link boundary."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import LinkFetcher, SessionStore
from toolbox.core.errors import InvalidRequest, ProviderUnavailable, ToolboxError
from toolbox.core.models import (
    ActionKind,
    ErrorResult,
    SourceRef,
    TextResult,
    ToolRequest,
    ToolResult,
)


class SearchExpandCapability:
    """Show a small bounded extract from the selected search result."""

    def __init__(
        self,
        *,
        fetcher: LinkFetcher,
        sessions: SessionStore,
        max_chars: int = 1_800,
    ) -> None:
        self._fetcher = fetcher
        self._sessions = sessions
        self._max_chars = max(400, min(max_chars, 3_000))

    async def execute(self, request: ToolRequest) -> ToolResult:
        if request.session_id is None:
            return self._error(InvalidRequest)
        session = await self._sessions.get(
            request.actor.user.user_id,
            request.session_id,
        )
        if session is None or session.action is not ActionKind.EXPAND:
            return self._error(InvalidRequest)

        url = session.payload.get("url", "").strip()
        if not url:
            return self._error(InvalidRequest)
        try:
            document = await self._fetcher.fetch(url)
        except ToolboxError as error:
            return self._error(error)

        text = self._compact(document.text)
        if not text:
            return self._error(ProviderUnavailable)
        await self._sessions.delete(request.actor.user.user_id, request.session_id)
        title = document.title or session.payload.get("title") or "Search result"
        return TextResult(
            title=title,
            text=text,
            input_text=session.payload.get("query") or None,
            sources=(
                SourceRef(
                    title=title,
                    url=document.url,
                    source_name=session.payload.get("source_name") or None,
                ),
            ),
            actions=(share_action(),),
        )

    def _compact(self, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) <= self._max_chars:
            return normalized
        return f"{normalized[: self._max_chars - 1]}…"

    @staticmethod
    def _error(error_type: type[ToolboxError] | ToolboxError) -> ErrorResult:
        error = error_type() if isinstance(error_type, type) else error_type
        return ErrorResult(code=error.code, message=error.user_message, retryable=error.retryable)
