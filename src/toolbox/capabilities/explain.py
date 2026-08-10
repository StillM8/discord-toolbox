"""Universal explanation/definition capability for explicit Discord targets."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import AIService
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AIProfile,
    ErrorResult,
    LLMRequest,
    TextResult,
    ToolRequest,
    ToolResult,
)


class WhatIsThisCapability:
    """Explain a selected message or explicit text without reading surrounding history."""

    def __init__(self, ai: AIService) -> None:
        self._ai = ai

    async def execute(self, request: ToolRequest) -> ToolResult:
        target = request.target_message.content if request.target_message is not None else ""
        subject = (request.text or target).strip()
        if not subject or len(subject) > 20_000:
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message="Select something or tell me what to explain.",
            )
        try:
            response = await self._ai.generate(
                AIProfile.NORMAL,
                LLMRequest(
                    system=(
                        "Explain the supplied Discord content. Identify whether it is a term, "
                        "claim, person, technology, error, link, or phrase when useful. "
                        "Be concise, state uncertainty, and do not invent context."
                    ),
                    input=f"CONTENT TO EXPLAIN:\n{subject}",
                    max_output_tokens=1_200,
                ),
            )
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="That explanation request is not valid.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return TextResult(
            title="What is this?",
            text=response.text,
            input_text=subject,
            actions=(share_action(),),
        )
