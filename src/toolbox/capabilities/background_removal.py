"""Application capability for optional local background removal."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import (
    AssetStore,
    AttachmentIngestor,
    BackgroundRemovalProvider,
)
from toolbox.core.errors import ToolboxError
from toolbox.core.models import ErrorResult, ImageResult, ToolRequest, ToolResult


class BackgroundRemovalCapability:
    """Validate an image attachment, remove its background, and own the result."""

    def __init__(
        self,
        provider: BackgroundRemovalProvider,
        assets: AssetStore,
        ingestor: AttachmentIngestor,
    ) -> None:
        self._provider = provider
        self._assets = assets
        self._ingestor = ingestor

    async def execute(self, request: ToolRequest) -> ToolResult:
        attachment = self._attachment(request)
        if attachment is None:
            return ErrorResult(code="invalid_request", message="Attach one image first.")
        try:
            source = await self._ingestor.ingest(attachment, request.actor.user.user_id)
            data = await self._assets.read(source)
            generated = await self._provider.remove(data, source.mime_type)
            asset = await self._assets.put(
                generated.data,
                owner_id=request.actor.user.user_id,
                mime_type=generated.mime_type,
            )
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return ImageResult(
            asset=asset,
            title="Background removed",
            actions=(share_action(),),
        )

    @staticmethod
    def _attachment(request: ToolRequest):
        if request.attachments:
            return request.attachments[0]
        if request.target_message is not None and request.target_message.attachments:
            return request.target_message.attachments[0]
        return None
