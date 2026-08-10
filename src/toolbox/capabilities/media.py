"""Attachment-backed OCR and deterministic image transformations."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import (
    AssetStore,
    AttachmentIngestor,
    ImageAttachmentIngestor,
    ImageProcessor,
    OCRProvider,
)
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AssetRef,
    ErrorResult,
    ImageResult,
    TextResult,
    ToolRequest,
    ToolResult,
)


class ImageAssetCapability:
    """Apply a bounded local image operation to one explicit image input."""

    def __init__(
        self,
        assets: AssetStore,
        ingestor: ImageAttachmentIngestor | None = None,
        processor: ImageProcessor | None = None,
    ) -> None:
        self._assets = assets
        self._ingestor = ingestor
        self._processor = processor

    async def execute(self, request: ToolRequest) -> ToolResult:
        try:
            if self._processor is None:
                raise InvalidRequest
            operation = request.options.get("operation", "sanitize")
            options = dict(request.options)
            if operation == "meme" and not options.get("top") and not options.get("bottom"):
                options["bottom"] = (
                    request.target_message.content[:200]
                    if request.target_message is not None
                    else ""
                )
            source = self._context_asset(request)
            if source is not None:
                transformed = await self._processor.transform(
                    await self._assets.read(source),
                    operation,
                    options,
                )
                asset = await self._assets.put(
                    transformed,
                    owner_id=request.actor.user.user_id,
                    mime_type="image/png",
                    ttl_seconds=1_800,
                )
            else:
                attachment = self._attachment(request)
                if self._ingestor is None or attachment is None:
                    raise InvalidRequest
                # The remote path performs download, validation, decoding,
                # transformation, and ownership in one pipeline.  This avoids
                # creating a sanitized intermediate image only to decode it
                # again for the requested local operation.
                asset = await self._ingestor.ingest_transformed(
                    attachment,
                    request.actor.user.user_id,
                    operation=operation,
                    options=options,
                )
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="Select a supported image first.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return ImageResult(
            asset=asset,
            title=f"Image · {operation}",
            actions=(share_action(),),
        )

    @staticmethod
    def _context_asset(request: ToolRequest) -> AssetRef | None:
        for item in request.context_items:
            if item.asset is not None:
                return item.asset
        return None

    @staticmethod
    def _attachment(request: ToolRequest):
        if request.target_message is not None and request.target_message.attachments:
            return request.target_message.attachments[0]
        if request.attachments:
            return request.attachments[0]
        return None


class OCRCapability:
    """Extract text from one validated image asset through an OCR provider."""

    def __init__(
        self,
        assets: AssetStore,
        provider: OCRProvider,
        ingestor: AttachmentIngestor | None = None,
    ) -> None:
        self._assets = assets
        self._provider = provider
        self._ingestor = ingestor

    async def execute(self, request: ToolRequest) -> ToolResult:
        try:
            source = await self._source_asset(request)
            result = await self._provider.extract(
                await self._assets.read(source),
                source.mime_type,
            )
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="Select a supported image first.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        if not result.text.strip():
            return TextResult(title="OCR", text="No text was found.")
        return TextResult(title="OCR", text=result.text, actions=(share_action(),))

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
