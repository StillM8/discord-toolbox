"""Ask a bounded vision question about one explicit image."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import AIService, AssetStore, AttachmentIngestor
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AIProfile,
    AssetRef,
    ErrorResult,
    LLMRequest,
    TextResult,
    ToolRequest,
    ToolResult,
)


class ImageQuestionCapability:
    """Use the configured vision profile without exposing a provider to Discord."""

    def __init__(
        self,
        ai: AIService,
        assets: AssetStore,
        ingestor: AttachmentIngestor | None = None,
    ) -> None:
        self._ai = ai
        self._ingestor = ingestor

    async def execute(self, request: ToolRequest) -> ToolResult:
        try:
            asset = await self._source_asset(request)
            question = (
                request.text or "Describe this image and point out anything important."
            ).strip()
            if len(question) > 2_000:
                raise InvalidRequest
            response = await self._ai.generate(
                AIProfile.VISION,
                LLMRequest(
                    system=(
                        "You analyze only the supplied image. Be concise, describe uncertainty, "
                        "and do not claim to know hidden conversation context."
                    ),
                    input=question,
                    images=(asset,),
                    max_output_tokens=1_200,
                ),
            )
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="Select a supported image first.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return TextResult(
            title="Image answer",
            text=response.text,
            input_text=request.text or "Selected image",
            actions=(share_action(),),
        )

    async def _source_asset(self, request: ToolRequest) -> AssetRef:
        for item in request.context_items:
            if item.asset is not None:
                return item.asset
        if request.target_message is not None and request.target_message.attachments:
            if self._ingestor is None:
                raise InvalidRequest
            return await self._ingestor.ingest(
                request.target_message.attachments[0],
                request.actor.user.user_id,
            )
        if request.attachments:
            if self._ingestor is None:
                raise InvalidRequest
            return await self._ingestor.ingest(request.attachments[0], request.actor.user.user_id)
        raise InvalidRequest
