from __future__ import annotations

import io
from typing import cast
from uuid import uuid4

import pytest
from PIL import Image

from toolbox.capabilities.quote import QuoteCapability
from toolbox.core.models import (
    ActorContext,
    AssetRef,
    AttachmentRef,
    CapabilityName,
    ImageResult,
    InteractionContext,
    MessageContext,
    QuoteCardRequest,
    QuoteColorMode,
    QuoteFont,
    QuoteImageMode,
    QuoteStyle,
    QuoteTextPosition,
    ToolRequest,
    UserContext,
    UserPreferences,
)
from toolbox.infrastructure.media import LocalQuoteCardProcessor


class Assets:
    async def put(
        self,
        data: bytes,
        *,
        owner_id: int,
        mime_type: str,
        ttl_seconds: int | None = None,
    ) -> AssetRef:
        del data, ttl_seconds
        return AssetRef(uuid4(), mime_type, 3, owner_id)

    async def read(self, asset: AssetRef) -> bytes:
        del asset
        return b"png"

    async def delete(self, asset: AssetRef) -> None:
        del asset


class QuoteRenderer:
    def __init__(self) -> None:
        self.request: QuoteCardRequest | None = None
        self.image_data: bytes | None = None

    async def render(
        self,
        request: QuoteCardRequest,
        image_data: bytes | None = None,
    ) -> bytes:
        self.request = request
        self.image_data = image_data
        return b"png"


class ImageIngestor:
    def __init__(self) -> None:
        self.attachments: list[AttachmentRef] = []

    async def ingest(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        del owner_id
        self.attachments.append(attachment)
        return AssetRef(uuid4(), "image/png", 3, 42)


class Preferences:
    def __init__(self) -> None:
        self.value = UserPreferences(owner_id=42)

    async def get(self, owner_id: int) -> UserPreferences:
        assert owner_id == 42
        return self.value

    async def save(self, preferences: UserPreferences) -> None:
        self.value = preferences


@pytest.mark.asyncio
async def test_quote_capability_uses_selected_message_text_and_author() -> None:
    renderer = QuoteRenderer()
    message = MessageContext(
        message_id=1,
        author_id=99,
        author_name="Quoted Person",
        content="This belongs in a quote card.",
        channel_id=2,
        guild_id=3,
        reply_to_message_id=None,
    )
    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.QUOTE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=3, channel_id=2, surface="guild"),
        target_message=message,
    )

    result = await QuoteCapability(renderer, Assets()).execute(request)

    assert isinstance(result, ImageResult)
    assert result.input_text is None
    assert renderer.request is not None
    assert renderer.request.quote == message.content
    assert renderer.request.author == message.author_name
    assert renderer.request.style.image_mode is QuoteImageMode.LEFT


@pytest.mark.asyncio
async def test_quote_capability_accepts_explicit_text_and_attribution() -> None:
    renderer = QuoteRenderer()
    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.QUOTE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=2, surface="dm"),
        text="A custom quote.",
        options={"author": "Someone"},
    )

    result = await QuoteCapability(renderer, Assets()).execute(request)

    assert isinstance(result, ImageResult)
    assert renderer.request is not None
    assert renderer.request.quote == "A custom quote."
    assert renderer.request.author == "Someone"


@pytest.mark.asyncio
async def test_quote_capability_keeps_unicode_and_readable_custom_emojis() -> None:
    renderer = QuoteRenderer()
    message = MessageContext(
        message_id=2,
        author_id=99,
        author_name="Emoji Person",
        content="Hello 😀 <:party:12345>",
        channel_id=2,
        guild_id=3,
        reply_to_message_id=None,
    )
    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.QUOTE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=3, channel_id=2, surface="guild"),
        target_message=message,
    )

    result = await QuoteCapability(renderer, Assets()).execute(request)

    assert isinstance(result, ImageResult)
    assert renderer.request is not None
    assert renderer.request.quote == "Hello 😀 :party:"


@pytest.mark.asyncio
async def test_quote_capability_normalizes_style_and_ingests_selected_image() -> None:
    renderer = QuoteRenderer()
    ingestor = ImageIngestor()
    image = AttachmentRef(
        attachment_id="image-1",
        source_url="https://cdn.example/image.png",
        filename="image.png",
        declared_content_type="image/png",
        declared_size=10,
    )
    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.QUOTE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=3, channel_id=2, surface="guild"),
        text="Styled quote",
        attachments=(image,),
        options={
            "font": "serif",
            "text_position": "right",
            "color_mode": "color",
            "image_mode": "background",
        },
    )

    result = await QuoteCapability(renderer, Assets(), ingestor).execute(request)

    assert isinstance(result, ImageResult)
    assert ingestor.attachments == [image]
    assert renderer.request is not None
    assert renderer.request.style == QuoteStyle(
        font=QuoteFont.SERIF,
        text_position=QuoteTextPosition.RIGHT,
        color_mode=QuoteColorMode.COLOR,
        image_mode=QuoteImageMode.BACKGROUND,
    )


@pytest.mark.asyncio
async def test_quote_capability_does_not_download_when_image_is_hidden() -> None:
    renderer = QuoteRenderer()
    ingestor = ImageIngestor()
    image = AttachmentRef(
        attachment_id="image-1",
        source_url="https://cdn.example/image.png",
        filename="image.png",
        declared_content_type="image/png",
        declared_size=10,
    )
    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.QUOTE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=2, surface="dm"),
        text="No image quote",
        attachments=(image,),
        options={"image_mode": "hidden"},
    )

    result = await QuoteCapability(renderer, Assets(), ingestor).execute(request)

    assert isinstance(result, ImageResult)
    assert ingestor.attachments == []
    assert renderer.image_data is None


@pytest.mark.asyncio
async def test_quote_capability_remembers_the_last_style() -> None:
    renderer = QuoteRenderer()
    preferences = Preferences()
    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.QUOTE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=2, surface="dm"),
        text="Remember this style",
        options={
            "font": "serif",
            "text_position": "right",
            "color_mode": "color",
            "image_mode": "background",
        },
    )

    result = await QuoteCapability(renderer, Assets(), None, preferences).execute(request)

    assert isinstance(result, ImageResult)
    assert preferences.value.quote_font is QuoteFont.SERIF
    assert preferences.value.quote_text_position is QuoteTextPosition.RIGHT
    assert preferences.value.quote_color_mode is QuoteColorMode.COLOR
    assert preferences.value.quote_image_mode is QuoteImageMode.BACKGROUND


@pytest.mark.asyncio
async def test_local_quote_card_processor_returns_normalized_image() -> None:
    data = await LocalQuoteCardProcessor().render(
        QuoteCardRequest(quote="A local quote.", author="Toolbox")
    )

    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (1_280, 720)
        assert image.format == "PNG"


@pytest.mark.asyncio
async def test_local_quote_card_processor_composes_a_reference_style_image() -> None:
    source = io.BytesIO()
    Image.new("RGB", (400, 300), (220, 40, 40)).save(source, format="PNG")
    data = await LocalQuoteCardProcessor().render(
        QuoteCardRequest(
            quote="A styled quote.",
            author="Someone",
            style=QuoteStyle(
                font=QuoteFont.SERIF,
                text_position=QuoteTextPosition.LEFT,
                color_mode=QuoteColorMode.COLOR,
                image_mode=QuoteImageMode.LEFT,
            ),
        ),
        source.getvalue(),
    )

    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (1_280, 720)
        left_pixel = cast(tuple[int, ...], image.getpixel((80, 360)))
        right_pixel = cast(tuple[int, ...], image.getpixel((1_200, 360)))
        assert left_pixel[:3] == (220, 40, 40)
        assert right_pixel[:3] == (0, 0, 0)
        boundary_pixel = cast(tuple[int, ...], image.getpixel((640, 360)))
        assert boundary_pixel[:3] == (0, 0, 0)


@pytest.mark.asyncio
async def test_local_quote_card_processor_supports_hidden_image() -> None:
    source = io.BytesIO()
    Image.new("RGB", (400, 300), (220, 40, 40)).save(source, format="PNG")
    data = await LocalQuoteCardProcessor().render(
        QuoteCardRequest(
            quote="No photo.",
            author="Someone",
            style=QuoteStyle(image_mode=QuoteImageMode.HIDDEN),
        ),
        source.getvalue(),
    )

    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (1_280, 720)
        pixel = cast(tuple[int, ...], image.getpixel((80, 360)))
        assert pixel[:3] == (0, 0, 0)
