from __future__ import annotations

import base64
import io
from collections.abc import Mapping
from typing import cast
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from toolbox.capabilities.image_edit import ImageEditCapability
from toolbox.capabilities.image_generation import ImageGenerationCapability
from toolbox.capabilities.image_question import ImageQuestionCapability
from toolbox.capabilities.media import ImageAssetCapability, OCRCapability
from toolbox.core.errors import ProviderUnavailable
from toolbox.core.models import (
    ActorContext,
    AIProfile,
    AssetRef,
    AttachmentRef,
    CapabilityName,
    GeneratedImage,
    ImageEditRequest,
    ImageGenerationRequest,
    ImageResult,
    InteractionContext,
    LLMRequest,
    LLMResponse,
    OCRResult,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.infrastructure.attachments import AttachmentIngestor
from toolbox.infrastructure.media import ImageProcessor
from toolbox.infrastructure.url_policy import RemoteUrlPolicy
from toolbox.providers.images.openai import OpenAIImageProvider, OpenAIImagesClient
from toolbox.providers.images.unavailable import UnavailableImageGenerationProvider


def png_bytes(size: tuple[int, int] = (20, 10)) -> bytes:
    image = Image.new("RGBA", size, (255, 0, 0, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class Assets:
    def __init__(self, data: bytes = b"") -> None:
        self.data = data
        self.put_count = 0
        self.asset = AssetRef(uuid4(), "image/png", len(data), 42)

    async def put(
        self,
        data: bytes,
        *,
        owner_id: int,
        mime_type: str,
        ttl_seconds: int | None = None,
    ) -> AssetRef:
        del owner_id, ttl_seconds
        self.put_count += 1
        self.data = data
        self.asset = AssetRef(uuid4(), mime_type, len(data), 42)
        return self.asset

    async def read(self, asset: AssetRef) -> bytes:
        assert asset.asset_id == self.asset.asset_id
        return self.data

    async def delete(self, asset: AssetRef) -> None:
        del asset


def request(
    capability: CapabilityName,
    *,
    context_asset: AssetRef | None = None,
    options: Mapping[str, str] | None = None,
    attachments: tuple[AttachmentRef, ...] = (),
) -> ToolRequest:
    from toolbox.core.models import ContextItem

    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        context_items=(
            ContextItem(item_id=uuid4(), owner_id=42, label="image", asset=context_asset),
        )
        if context_asset is not None
        else (),
        attachments=attachments,
        options=options or {},
    )


@pytest.mark.asyncio
async def test_image_processor_transform_is_deterministic_and_bounded() -> None:
    output = await ImageProcessor().transform(
        png_bytes((100, 50)),
        "resize",
        {"width": "20", "height": "20"},
    )

    with Image.open(io.BytesIO(output)) as image:
        assert image.width <= 20
        assert image.height <= 20


@pytest.mark.asyncio
async def test_image_processor_supports_fast_grayscale_edit() -> None:
    output = await ImageProcessor().transform(png_bytes(), "grayscale")

    with Image.open(io.BytesIO(output)) as image:
        red, green, blue = cast(tuple[int, int, int], image.convert("RGB").getpixel((0, 0)))
        assert red == green == blue


@pytest.mark.asyncio
async def test_attachment_ingestor_validates_and_owns_remote_image() -> None:
    source = png_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        return httpx.Response(200, content=source, headers={"content-length": str(len(source))})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    assets = Assets()
    try:
        policy = RemoteUrlPolicy(resolver=lambda host, port: ("93.184.216.34",))
        asset = await AttachmentIngestor(client, assets, url_policy=policy).ingest(
            AttachmentRef(
                "1",
                "https://cdn.example/image.png",
                "image.png",
                "image/png",
                len(source),
            ),
            42,
        )
    finally:
        await client.aclose()

    assert asset.mime_type == "image/png"
    assert Image.open(io.BytesIO(assets.data)).format == "PNG"


@pytest.mark.asyncio
async def test_image_capability_uses_explicit_asset_and_returns_shareable_result() -> None:
    assets = Assets(png_bytes())
    result = await ImageAssetCapability(assets, processor=ImageProcessor()).execute(
        request(
            CapabilityName.IMAGE_EDIT,
            context_asset=assets.asset,
            options={"operation": "mirror"},
        )
    )

    assert isinstance(result, ImageResult)
    assert result.asset.owner_id == 42


@pytest.mark.asyncio
async def test_meme_operation_is_local_and_returns_an_owned_asset() -> None:
    assets = Assets(png_bytes((240, 120)))
    result = await ImageAssetCapability(assets, processor=ImageProcessor()).execute(
        request(
            CapabilityName.IMAGE_MEME,
            context_asset=assets.asset,
            options={"operation": "meme", "top": "WHEN TESTS", "bottom": "ARE GREEN"},
        )
    )

    assert isinstance(result, ImageResult)
    with Image.open(io.BytesIO(assets.data)) as image:
        assert image.format == "PNG"
        assert image.size == (1_280, 720)


@pytest.mark.asyncio
async def test_meme_normalizes_different_source_sizes_to_720p() -> None:
    processor = ImageProcessor()

    for source_size in ((240, 120), (1_920, 1_080), (4_000, 3_000)):
        output = await processor.transform(
            png_bytes(source_size),
            "meme",
            {"top": "TOP", "bottom": "BOTTOM"},
        )

        with Image.open(io.BytesIO(output)) as image:
            assert image.size == (1_280, 720)


@pytest.mark.asyncio
async def test_remote_meme_transforms_and_stores_the_image_once() -> None:
    source = png_bytes((240, 120))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        return httpx.Response(200, content=source, headers={"content-length": str(len(source))})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    assets = Assets()
    ingestor = AttachmentIngestor(
        client,
        assets,
        url_policy=RemoteUrlPolicy(resolver=lambda host, port: ("93.184.216.34",)),
    )
    try:
        result = await ImageAssetCapability(
            assets,
            ingestor=ingestor,
            processor=ImageProcessor(),
        ).execute(
            request(
                CapabilityName.IMAGE_MEME,
                attachments=(
                    AttachmentRef(
                        "meme-1",
                        "https://cdn.example/image.png",
                        "image.png",
                        "image/png",
                        len(source),
                    ),
                ),
                options={"operation": "meme", "top": "TOP", "bottom": "BOTTOM"},
            )
        )
    finally:
        await client.aclose()

    assert isinstance(result, ImageResult)
    assert assets.put_count == 1
    with Image.open(io.BytesIO(assets.data)) as image:
        assert image.size == (1_280, 720)


@pytest.mark.asyncio
async def test_meme_supports_1080p_and_scales_caption_size_with_canvas() -> None:
    processor = ImageProcessor()
    output_720 = await processor.transform(
        png_bytes((240, 120)),
        "meme",
        {"top": "TOP", "bottom": "BOTTOM"},
    )
    output_1080 = await processor.transform(
        png_bytes((240, 120)),
        "meme",
        {"resolution": "1080p", "top": "TOP", "bottom": "BOTTOM"},
    )

    def caption_width(output: bytes) -> int:
        with Image.open(io.BytesIO(output)).convert("RGB") as image:
            white_x = [
                x
                for y in range(image.height)
                for x in range(image.width)
                if (
                    isinstance((pixel := image.getpixel((x, y))), tuple)
                    and len(pixel) >= 3
                    and all(channel > 245 for channel in pixel[:3])
                )
            ]
        return max(white_x) - min(white_x)

    with Image.open(io.BytesIO(output_720)) as image:
        assert image.size == (1_280, 720)
    with Image.open(io.BytesIO(output_1080)) as image:
        assert image.size == (1_920, 1_080)

    assert caption_width(output_1080) > caption_width(output_720) * 1.35


@pytest.mark.asyncio
async def test_caption_adds_a_panel_above_a_normalized_image() -> None:
    output = await ImageProcessor().transform(
        png_bytes((240, 120)),
        "caption",
        {"caption": "A caption above the image"},
    )

    with Image.open(io.BytesIO(output)) as image:
        assert image.size[0] == 1_280
        assert image.size[1] > 720


@pytest.mark.asyncio
async def test_meme_can_include_a_caption_panel_and_meme_text() -> None:
    output = await ImageProcessor().transform(
        png_bytes((240, 120)),
        "meme",
        {"caption": "Above the image", "top": "TOP", "bottom": "BOTTOM"},
    )

    with Image.open(io.BytesIO(output)) as image:
        assert image.size[0] == 1_280
        assert image.size[1] > 720


@pytest.mark.asyncio
async def test_image_question_requests_the_vision_profile() -> None:
    class AI:
        async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
            assert profile is AIProfile.VISION
            assert len(request.images) == 1
            return LLMResponse(text="It is a red square.")

    assets = Assets(png_bytes())
    result = await ImageQuestionCapability(AI(), assets).execute(
        request(CapabilityName.IMAGE_ASK, context_asset=assets.asset)
    )

    assert isinstance(result, TextResult)
    assert result.text == "It is a red square."


@pytest.mark.asyncio
async def test_ocr_capability_normalizes_provider_text() -> None:
    class OCR:
        async def extract(self, data: bytes, mime_type: str) -> OCRResult:
            assert data
            assert mime_type == "image/png"
            return OCRResult("hello")

    assets = Assets(png_bytes())
    result = await OCRCapability(assets, OCR()).execute(
        request(CapabilityName.IMAGE_OCR, context_asset=assets.asset)
    )

    assert isinstance(result, TextResult)
    assert result.text == "hello"


@pytest.mark.asyncio
async def test_openai_image_provider_decodes_provider_image() -> None:
    class Data:
        b64_json = base64.b64encode(png_bytes()).decode("ascii")
        url = None

    class Response:
        data = [Data()]

    class Images:
        async def generate(self, **kwargs: object) -> Response:
            assert kwargs["model"] == "gpt-image-2"
            return Response()

    class Client:
        images = Images()

    generated = await OpenAIImageProvider(
        client=cast(OpenAIImagesClient, Client()),
        model="gpt-image-2",
    ).generate(ImageGenerationRequest("a cat"))

    assert isinstance(generated, GeneratedImage)
    assert generated.mime_type == "image/png"
    assert generated.data.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_image_generation_capability_stores_generated_asset() -> None:
    class Provider:
        async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
            del request
            return GeneratedImage(png_bytes(), "image/png")

    assets = Assets()
    result = await ImageGenerationCapability(Provider(), assets).execute(
        ToolRequest(
            request_id=uuid4(),
            capability=CapabilityName.IMAGE_GENERATE,
            actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
            interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
            text="a cat",
        )
    )

    assert isinstance(result, ImageResult)
    assert assets.data.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_image_edit_capability_uses_provider_boundary_and_asset_store() -> None:
    class Provider:
        async def edit(self, request: ImageEditRequest) -> GeneratedImage:
            assert request.asset.owner_id == 42
            assert request.prompt == "make it blue"
            return GeneratedImage(png_bytes(), "image/png")

    assets = Assets(png_bytes())
    result = await ImageEditCapability(Provider(), assets).execute(
        request(
            CapabilityName.IMAGE_EDIT_AI,
            context_asset=assets.asset,
            options={"prompt": "make it blue"},
        )
    )

    assert isinstance(result, ImageResult)
    assert result.asset.owner_id == 42


@pytest.mark.asyncio
async def test_image_edit_capability_uses_local_processor_for_fast_operation() -> None:
    class Provider:
        async def edit(self, request: ImageEditRequest) -> GeneratedImage:
            del request
            raise AssertionError("deterministic edit should not call AI")

    class LocalProcessor:
        async def transform(
            self,
            data: bytes,
            operation: str,
            options: Mapping[str, str] | None = None,
            *,
            max_pixels: int = 20_000_000,
        ) -> bytes:
            assert data
            assert operation == "grayscale"
            assert options == {}
            assert max_pixels == 20_000_000
            return png_bytes()

    assets = Assets(png_bytes())
    result = await ImageEditCapability(
        Provider(),
        assets,
        local_processor=cast(ImageProcessor, LocalProcessor()),
    ).execute(
        request(
            CapabilityName.IMAGE_EDIT_AI,
            context_asset=assets.asset,
            options={"prompt": "make it black and white"},
        )
    )

    assert isinstance(result, ImageResult)
    assert result.title == "Quick edit · grayscale"


@pytest.mark.asyncio
async def test_unconfigured_image_provider_is_explicitly_unavailable() -> None:
    with pytest.raises(ProviderUnavailable):
        await UnavailableImageGenerationProvider().generate(
            ImageGenerationRequest("a cat")
        )
