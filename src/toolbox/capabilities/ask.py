"""General ask/explain capability backed by the application AI contract."""

from __future__ import annotations

from dataclasses import replace

from toolbox.core.actions import share_action
from toolbox.core.contracts import AIService, ContextStore
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AIProfile,
    ErrorResult,
    LLMRequest,
    TextResult,
    ToolRequest,
    ToolResult,
)


class AskPromptBuilder:
    """Format complete structured input; it does not retrieve or persist data."""

    def build(self, request: ToolRequest) -> LLMRequest:
        pieces: list[str] = []
        if request.target_message is not None:
            pieces.append(
                "TARGET MESSAGE:\n"
                f"author={request.target_message.author_name}\n"
                f"content={request.target_message.content}"
            )
        for item in request.context_items:
            if item.message is not None:
                pieces.append(f"SELECTED CONTEXT ({item.label}):\n{item.message.content}")
            elif item.text:
                pieces.append(f"SELECTED CONTEXT ({item.label}):\n{item.text}")
        if request.text:
            pieces.append(f"QUESTION:\n{request.text}")
        if not pieces:
            raise InvalidRequest
        return LLMRequest(
            system=(
                "You are Toolbox, a concise Discord utility assistant. "
                "Answer the explicit request using only the supplied context. "
                "Do not claim to have seen surrounding Discord history."
            ),
            input="\n\n".join(pieces),
            images=tuple(item.asset for item in request.context_items if item.asset is not None),
            max_output_tokens=1_500,
        )


class AskCapability:
    """Answer a direct question or a question about selected context."""

    def __init__(
        self,
        ai: AIService,
        prompt_builder: AskPromptBuilder | None = None,
        context_store: ContextStore | None = None,
    ) -> None:
        self._ai = ai
        self._prompt_builder = prompt_builder or AskPromptBuilder()
        self._context_store = context_store

    async def execute(self, request: ToolRequest) -> ToolResult:
        try:
            context_request = request
            if self._context_store is not None and not request.context_items:
                context_items = await self._context_store.list(request.actor.user.user_id)
                context_request = replace(request, context_items=tuple(context_items))
            llm_request = self._prompt_builder.build(context_request)
            profile = AIProfile.VISION if llm_request.images else AIProfile.NORMAL
            response = await self._ai.generate(profile, llm_request)
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="Tell me what you want me to answer.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return TextResult(
            title="Toolbox",
            text=response.text,
            input_text=request.text or "Selected context",
            actions=(share_action(),),
        )
