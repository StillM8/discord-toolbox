from __future__ import annotations

import io
from uuid import uuid4

import pytest
from PIL import Image

from toolbox.capabilities.emoji import EmojiCapability
from toolbox.core.models import (
    ActorContext,
    AssetRef,
    AttachmentRef,
    CapabilityName,
    EmojiRenderRequest,
    ImageResult,
    InteractionContext,
    ToolRequest,
    UserContext,
)
from toolbox.infrastructure.media import LocalEmojiProcessor


class Assets:
    def __init__(self) -> None:
        self.data: bytes | None = None

    async def put(
        self,
        data: bytes,
        *,
        owner_id: int,
        mime_type: str,
        ttl_seconds: int | None = None,
    ) -> AssetRef:
        del owner_id, mime_type, ttl_seconds
        self.data = data
        return AssetRef(uuid4(), "image/png", len(data), 42)

    async def read(self, asset: AssetRef) -> bytes:
        del asset
        return self.data or b"source"

    async def delete(self, asset: AssetRef) -> None:
        del asset


class Processor:
    def __init__(self) -> None:
        self.request: EmojiRenderRequest | None = None
        self.image_data: bytes | None = None

    async def render(
        self,
        request: EmojiRenderRequest,
        image_data: bytes | None = None,
    ) -> bytes:
        self.request = request
        self.image_data = image_data
        return b"png"


class Ingestor:
    def __init__(self) -> None:
        self.attachment: AttachmentRef | None = None

    async def ingest(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        del owner_id
        self.attachment = attachment
        return AssetRef(uuid4(), "image/png", 3, 42)


def request(value: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.EMOJI,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        text=value,
        options={"value": value},
    )


@pytest.mark.asyncio
async def test_emoji_capability_preserves_unicode_input() -> None:
    processor = Processor()
    result = await EmojiCapability(processor, Assets()).execute(request("😀"))

    assert isinstance(result, ImageResult)
    assert processor.request == EmojiRenderRequest(value="😀", size=512)
    assert processor.image_data is None


@pytest.mark.asyncio
async def test_emoji_capability_downloads_custom_discord_emoji_once() -> None:
    processor = Processor()
    ingestor = Ingestor()
    result = await EmojiCapability(processor, Assets(), ingestor).execute(
        request("<a:party_dance:12345>")
    )

    assert isinstance(result, ImageResult)
    assert ingestor.attachment is not None
    assert ingestor.attachment.source_url == (
        "https://cdn.discordapp.com/emojis/12345.gif?size=256&quality=lossless"
    )
    assert ingestor.attachment.declared_content_type == "image/gif"
    assert processor.image_data == b"source"


@pytest.mark.asyncio
async def test_local_emoji_processor_returns_a_square_png() -> None:
    data = await LocalEmojiProcessor().render(EmojiRenderRequest(value="😀"))

    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "PNG"
        assert image.size == (512, 512)
