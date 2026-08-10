"""Attachment-backed bounded file conversion capability."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import AssetStore, FileProcessor, RawAttachmentIngestor
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import ErrorResult, FileResult, ToolRequest, ToolResult


class FileConvertCapability:
    """Convert an explicit attachment through a local file processor."""

    def __init__(
        self,
        assets: AssetStore,
        ingestor: RawAttachmentIngestor,
        processor: FileProcessor,
    ) -> None:
        self._assets = assets
        self._ingestor = ingestor
        self._processor = processor

    async def execute(self, request: ToolRequest) -> ToolResult:
        if len(request.attachments) != 1:
            return ErrorResult(
                code="invalid_request",
                message="Attach exactly one file to convert.",
            )
        target = request.options.get("target", "png").strip().lower().lstrip(".")
        if target not in {"png", "jpg", "jpeg", "webp", "gif", "pdf", "mp3", "wav", "mp4"}:
            return ErrorResult(
                code="invalid_request",
                message="That output format is not supported.",
            )
        try:
            source = await self._ingestor.ingest_raw(
                request.attachments[0],
                request.actor.user.user_id,
            )
            data = await self._assets.read(source)
            converted = await self._processor.convert(
                data,
                source_mime=source.mime_type,
                source_filename=request.attachments[0].filename,
                target_format=target,
            )
            asset = await self._assets.put(
                converted.data,
                owner_id=request.actor.user.user_id,
                mime_type=converted.mime_type,
                ttl_seconds=1_800,
            )
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="That file cannot be converted safely.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return FileResult(
            asset=asset,
            filename=converted.filename,
            title=f"Converted file · {converted.filename}",
            input_text=f"{request.attachments[0].filename} → {target}",
            actions=(share_action(),),
        )
