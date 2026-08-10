"""Transcribe explicitly selected audio through a replaceable provider."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import AssetStore, RawAttachmentIngestor, TranscriptionProvider
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import AssetRef, ErrorResult, TextResult, ToolRequest, ToolResult


class TranscribeCapability:
    """Turn one selected audio attachment/asset into bounded text."""

    def __init__(
        self,
        provider: TranscriptionProvider,
        assets: AssetStore,
        ingestor: RawAttachmentIngestor | None = None,
    ) -> None:
        self._provider = provider
        self._assets = assets
        self._ingestor = ingestor

    async def execute(self, request: ToolRequest) -> ToolResult:
        try:
            asset = await self._source_asset(request)
            if not asset.mime_type.startswith("audio/"):
                raise InvalidRequest
            result = await self._provider.transcribe(asset)
        except InvalidRequest as error:
            return ErrorResult(
                code=error.code,
                message="Select a supported audio attachment first.",
            )
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        text = result.text.strip()
        return TextResult(
            title="Transcription",
            text=text or "No speech was detected.",
            actions=(share_action(),),
        )

    async def _source_asset(self, request: ToolRequest) -> AssetRef:
        for item in request.context_items:
            if item.asset is not None:
                return item.asset
        if request.target_message is not None and request.target_message.attachments:
            if self._ingestor is None:
                raise InvalidRequest
            return await self._ingestor.ingest_raw(
                request.target_message.attachments[0],
                request.actor.user.user_id,
            )
        if request.attachments:
            if self._ingestor is None:
                raise InvalidRequest
            return await self._ingestor.ingest_raw(
                request.attachments[0],
                request.actor.user.user_id,
            )
        raise InvalidRequest
