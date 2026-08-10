"""Render Unicode and Discord custom emojis as shareable image assets."""

from __future__ import annotations

import re

from toolbox.core.actions import share_action
from toolbox.core.contracts import AssetStore, AttachmentIngestor, EmojiProcessor
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AssetRef,
    AttachmentRef,
    EmojiRenderRequest,
    ErrorResult,
    ImageResult,
    ToolRequest,
    ToolResult,
)

_CUSTOM_EMOJI = re.compile(r"^<(?P<animated>a?):(?P<name>[A-Za-z0-9_]+):(?P<id>\d+)>$")


class EmojiCapability:
    """Convert one explicit emoji value into a PNG result."""

    def __init__(
        self,
        processor: EmojiProcessor,
        assets: AssetStore,
        image_ingestor: AttachmentIngestor | None = None,
    ) -> None:
        self._processor = processor
        self._assets = assets
        self._image_ingestor = image_ingestor

    async def execute(self, request: ToolRequest) -> ToolResult:
        value = (request.text or request.options.get("value", "")).strip()
        if not value or len(value) > 100:
            return ErrorResult(
                code="invalid_request",
                message=(
                    "Enter one emoji or Discord custom emoji markup, such as "
                    "`😀` or `<:party:123>`."
                ),
            )

        try:
            image_data = await self._custom_emoji_data(value, request)
            data = await self._processor.render(
                EmojiRenderRequest(value=value, size=512),
                image_data,
            )
            asset = await self._assets.put(
                data,
                owner_id=request.actor.user.user_id,
                mime_type="image/png",
                ttl_seconds=3_600,
            )
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="That emoji could not be rendered safely.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )

        return ImageResult(
            asset=asset,
            title="Emoji",
            input_text=value,
            actions=(share_action(),),
        )

    async def _custom_emoji_data(self, value: str, request: ToolRequest) -> bytes | None:
        match = _CUSTOM_EMOJI.fullmatch(value)
        if match is None or self._image_ingestor is None:
            return None
        emoji_id = match.group("id")
        animated = bool(match.group("animated"))
        extension = "gif" if animated else "png"
        attachment = AttachmentRef(
            attachment_id=f"emoji:{emoji_id}",
            source_url=(
                f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}"
                "?size=256&quality=lossless"
            ),
            filename=f"{match.group('name')}.{extension}",
            declared_content_type="image/gif" if animated else "image/png",
            declared_size=0,
        )
        asset: AssetRef = await self._image_ingestor.ingest(
            attachment,
            request.actor.user.user_id,
        )
        return await self._assets.read(asset)
