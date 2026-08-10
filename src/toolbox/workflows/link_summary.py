"""Safe link fetching followed by explicit AI summarization."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from toolbox.core.actions import share_action
from toolbox.core.contracts import AIService, LinkFetcher
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AIProfile,
    ErrorResult,
    LLMRequest,
    TextResult,
    ToolRequest,
    ToolResult,
)


class LinkSummaryWorkflow:
    """Fetch one explicit link through the URL boundary, then summarize its text."""

    _url = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)

    def __init__(self, *, fetcher: LinkFetcher, ai: AIService) -> None:
        self._fetcher = fetcher
        self._ai = ai

    async def execute(self, request: ToolRequest) -> ToolResult:
        source = request.text or (
            request.target_message.content if request.target_message is not None else ""
        )
        match = self._url.search(source)
        if match is None:
            error = InvalidRequest
            return ErrorResult(code=error.code, message="Give me a message or URL to summarize.")
        url = match.group(0).rstrip(".,!?)]}")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            error = InvalidRequest
            return ErrorResult(code=error.code, message="That link is not valid.")
        try:
            document = await self._fetcher.fetch(url)
            response = await self._ai.generate(
                AIProfile.NORMAL,
                LLMRequest(
                    system=(
                        "Summarize the supplied document accurately and concisely. "
                        "Do not invent details that are not present in the document."
                    ),
                    input=(
                        f"URL: {document.url}\n"
                        f"TITLE: {document.title or 'Untitled'}\n\n"
                        f"{document.text}"
                    ),
                    max_output_tokens=1_200,
                ),
            )
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return TextResult(
            title=document.title or "Link summary",
            text=f"{response.text}\n\nSource: {document.url}",
            input_text=url,
            actions=(share_action(),),
        )
