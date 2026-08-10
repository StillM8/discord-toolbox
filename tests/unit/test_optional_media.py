from __future__ import annotations

import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from toolbox.capabilities.background_removal import BackgroundRemovalCapability
from toolbox.core.models import (
    ActorContext,
    AssetRef,
    AttachmentRef,
    CapabilityName,
    GeneratedImage,
    ImageResult,
    InteractionContext,
    ToolRequest,
    TranscriptionResult,
    UserContext,
)
from toolbox.providers.audio.faster_whisper import FasterWhisperTranscriptionProvider
from toolbox.providers.images.rembg import RembgBackgroundRemovalProvider


class Assets:
    def __init__(self, data: bytes = b"image") -> None:
        self.data = data
        self.asset = AssetRef(uuid4(), "image/png", len(data), 42)

    async def put(
        self,
        data: bytes,
        *,
        owner_id: int,
        mime_type: str,
        ttl_seconds: int | None = None,
    ) -> AssetRef:
        del ttl_seconds
        self.data = data
        self.asset = AssetRef(uuid4(), mime_type, len(data), owner_id)
        return self.asset

    async def read(self, asset: AssetRef) -> bytes:
        assert asset.asset_id == self.asset.asset_id
        return self.data

    async def delete(self, asset: AssetRef) -> None:
        del asset


def request() -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.IMAGE_BACKGROUND_REMOVE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        attachments=(
            AttachmentRef("a", "https://cdn.example/image.png", "image.png", "image/png", 5),
        ),
    )


@pytest.mark.asyncio
async def test_background_removal_capability_owns_generated_asset() -> None:
    assets = Assets()

    class Ingestor:
        async def ingest(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
            assert attachment.filename == "image.png"
            assert owner_id == 42
            return assets.asset

    class Provider:
        async def remove(self, data: bytes, mime_type: str) -> GeneratedImage:
            assert data == b"image"
            assert mime_type == "image/png"
            return GeneratedImage(b"png", "image/png")

    result = await BackgroundRemovalCapability(Provider(), assets, Ingestor()).execute(request())

    assert isinstance(result, ImageResult)
    assert assets.data == b"png"


@pytest.mark.asyncio
async def test_rembg_provider_normalizes_transparent_png(monkeypatch: pytest.MonkeyPatch) -> None:
    png = b"\x89PNG\r\n\x1a\noutput"
    def new_session(model: str) -> str:
        return model

    def remove(data: bytes, session: str) -> bytes:
        return png if data == b"input" and session == "u2net" else b"bad"

    fake_module = SimpleNamespace(new_session=new_session, remove=remove)
    monkeypatch.setitem(sys.modules, "rembg", fake_module)

    result = await RembgBackgroundRemovalProvider().remove(b"input", "image/png")

    assert result.data == png
    assert result.mime_type == "image/png"


@pytest.mark.asyncio
async def test_faster_whisper_provider_normalizes_local_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Segment:
        text = "hello"

    class Info:
        language = "en"

    class Model:
        def __init__(self, name: str, *, device: str, compute_type: str) -> None:
            assert (name, device, compute_type) == ("tiny", "cpu", "int8")

        def transcribe(self, path: str, *, beam_size: int):
            assert path.endswith(".wav")
            assert beam_size == 5
            return iter((Segment(), Segment())), Info()

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    assets = Assets(b"wav")
    assets.asset = AssetRef(uuid4(), "audio/wav", 3, 42)

    result = await FasterWhisperTranscriptionProvider(assets, model_size="tiny").transcribe(
        assets.asset
    )

    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello hello"
    assert result.language == "en"
