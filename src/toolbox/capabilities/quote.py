"""Create configurable, deterministic quote cards from explicit Discord input."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from enum import StrEnum
from typing import TypeVar

from toolbox.core.actions import share_action
from toolbox.core.contracts import (
    AssetStore,
    AttachmentIngestor,
    PreferencesRepository,
    QuoteCardProcessor,
)
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AttachmentRef,
    ErrorResult,
    ImageResult,
    QuoteCardRequest,
    QuoteColorMode,
    QuoteFont,
    QuoteImageMode,
    QuoteStyle,
    QuoteTextPosition,
    ToolRequest,
    ToolResult,
)

_CUSTOM_EMOJI = re.compile(r"<a?:([A-Za-z0-9_]+):\d+>")
_logger = logging.getLogger("toolbox.quote")


class QuoteCapability:
    """Normalize quote inputs, acquire an optional image, and render one card."""

    def __init__(
        self,
        processor: QuoteCardProcessor,
        assets: AssetStore,
        image_ingestor: AttachmentIngestor | None = None,
        preferences: PreferencesRepository | None = None,
    ) -> None:
        self._processor = processor
        self._assets = assets
        self._image_ingestor = image_ingestor
        self._preferences = preferences

    async def execute(self, request: ToolRequest) -> ToolResult:
        try:
            data = await self.render_preview(request)
            _, author = self._quote_and_author(request)
            asset = await self._assets.put(
                data,
                owner_id=request.actor.user.user_id,
                mime_type="image/png",
                ttl_seconds=3_600,
            )
            await self._remember_style(request, self._style_from_options(request.options))
        except InvalidRequest as error:
            return ErrorResult(
                code=error.code,
                message=(
                    "Select a message with text or provide a short quote, "
                    "and choose supported quote options."
                ),
            )
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )

        return ImageResult(
            asset=asset,
            title=f"Quote · {author or 'Toolbox'}",
            actions=(share_action(),),
        )

    async def render_preview(self, request: ToolRequest) -> bytes:
        """Render one deterministic preview without storing a result asset."""

        quote, author = self._quote_and_author(request)
        style = self._style_from_options(request.options)
        if not quote or len(quote) > 500:
            raise InvalidRequest
        image_data = await self._image_data(request, style)
        return await self._processor.render(
            QuoteCardRequest(
                quote=quote,
                author=author[:120],
                style=style,
            ),
            image_data,
        )

    async def _remember_style(self, request: ToolRequest, style: QuoteStyle) -> None:
        if self._preferences is None:
            return
        try:
            preferences = await self._preferences.get(request.actor.user.user_id)
            await self._preferences.save(
                replace(
                    preferences,
                    quote_font=style.font,
                    quote_text_position=style.text_position,
                    quote_color_mode=style.color_mode,
                    quote_image_mode=style.image_mode,
                )
            )
        except Exception:
            _logger.warning("quote_style_persist_failed", exc_info=True)

    @staticmethod
    def _quote_and_author(request: ToolRequest) -> tuple[str, str]:
        quote = _display_text(request.text or "")
        author = _display_text(request.options.get("author", ""))
        if request.target_message is not None:
            quote = quote or _display_text(request.target_message.content)
            author = author or _display_text(request.target_message.author_name)
        if request.target_user is not None:
            author = author or _display_text(request.target_user.display_name)
        if not author:
            author = _display_text(request.actor.user.display_name)
        return quote, author

    async def _image_data(self, request: ToolRequest, style: QuoteStyle) -> bytes | None:
        """Load one explicitly available image, without passing Discord objects inward."""

        if style.image_mode is QuoteImageMode.HIDDEN or self._image_ingestor is None:
            return None
        attachment = self._image_attachment(request)
        if attachment is None:
            attachment = self._avatar_attachment(request)
        if attachment is None:
            return None
        asset = await self._image_ingestor.ingest(
            attachment,
            request.actor.user.user_id,
        )
        return await self._assets.read(asset)

    @staticmethod
    def _image_attachment(request: ToolRequest) -> AttachmentRef | None:
        candidates = list(request.attachments)
        if request.target_message is not None:
            candidates.extend(request.target_message.attachments)
        for attachment in candidates:
            content_type = (attachment.declared_content_type or "").lower()
            filename = attachment.filename.lower()
            if content_type.startswith("image/") or filename.endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif")
            ):
                return attachment
        return None

    @staticmethod
    def _avatar_attachment(request: ToolRequest) -> AttachmentRef | None:
        if request.target_message is not None:
            avatar_url = request.target_message.author_avatar_url
            owner_id = request.target_message.author_id
        elif request.target_user is not None:
            avatar_url = request.target_user.avatar_url
            owner_id = request.target_user.user_id
        else:
            avatar_url = None
            owner_id = 0
        if not avatar_url:
            return None
        return AttachmentRef(
            attachment_id=f"avatar:{owner_id}",
            source_url=avatar_url,
            filename="avatar.png",
            declared_content_type="image/png",
            declared_size=0,
        )

    @staticmethod
    def _style_from_options(options: Mapping[str, str]) -> QuoteStyle:
        """Convert untrusted transport strings into bounded core enums."""

        font = QuoteCapability._enum_option(
            options.get("font"),
            QuoteFont,
            {
                "display": QuoteFont.DISPLAY,
                "modern": QuoteFont.SANS,
            },
            QuoteFont.SANS,
        )
        position = QuoteCapability._enum_option(
            options.get("text_position", options.get("position")),
            QuoteTextPosition,
            {},
            QuoteTextPosition.CENTER,
        )
        color = QuoteCapability._enum_option(
            options.get("color_mode", options.get("color")),
            QuoteColorMode,
            {
                "bw": QuoteColorMode.GRAYSCALE,
                "black_and_white": QuoteColorMode.GRAYSCALE,
                "black-white": QuoteColorMode.GRAYSCALE,
                "black and white": QuoteColorMode.GRAYSCALE,
            },
            QuoteColorMode.GRAYSCALE,
        )
        image = QuoteCapability._enum_option(
            options.get("image_mode", options.get("image")),
            QuoteImageMode,
            {
                "none": QuoteImageMode.HIDDEN,
                "background": QuoteImageMode.BACKGROUND,
            },
            QuoteImageMode.LEFT,
        )
        return QuoteStyle(
            font=font,
            text_position=position,
            color_mode=color,
            image_mode=image,
        )

    @staticmethod
    def _enum_option(
        value: str | None,
        enum_type: type[QuoteEnumT],
        aliases: Mapping[str, QuoteEnumT],
        default: QuoteEnumT,
    ) -> QuoteEnumT:
        if value is None or not value.strip():
            return default
        normalized = value.strip().lower()
        if normalized in aliases:
            return aliases[normalized]
        try:
            return enum_type(normalized)
        except ValueError as error:
            raise InvalidRequest from error


QuoteEnumT = TypeVar("QuoteEnumT", bound=StrEnum)


def _display_text(value: str) -> str:
    """Keep Unicode emoji and make custom Discord emoji markup readable."""

    return _CUSTOM_EMOJI.sub(lambda match: f":{match.group(1)}:", value).strip()
