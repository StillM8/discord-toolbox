from __future__ import annotations

import io
from uuid import uuid4

import pytest
from PIL import Image

from toolbox.capabilities.file_convert import FileConvertCapability
from toolbox.core.models import (
    ActorContext,
    AssetRef,
    AttachmentRef,
    CapabilityName,
    FileResult,
    InteractionContext,
    ToolRequest,
    UserContext,
)
from toolbox.infrastructure.file_processor import LocalFileProcessor


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (20, 10), (255, 0, 0, 255)).save(output, format="PNG")
    return output.getvalue()


class Assets:
    def __init__(self, data: bytes) -> None:
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


class RawIngestor:
    def __init__(self, asset: AssetRef) -> None:
        self.asset = asset

    async def ingest_raw(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        assert attachment.filename == "input.png"
        assert owner_id == 42
        return self.asset


@pytest.mark.asyncio
async def test_local_file_processor_converts_image_to_jpeg() -> None:
    result = await LocalFileProcessor().convert(
        _png(),
        source_mime="image/png",
        source_filename="input.png",
        target_format="jpg",
    )

    assert result.mime_type == "image/jpeg"
    assert result.filename == "input.jpg"
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.format == "JPEG"


@pytest.mark.asyncio
async def test_local_file_processor_round_trips_image_and_pdf() -> None:
    processor = LocalFileProcessor()
    pdf = await processor.convert(
        _png(),
        source_mime="image/png",
        source_filename="input.png",
        target_format="pdf",
    )
    assert pdf.mime_type == "application/pdf"

    image = await processor.convert(
        pdf.data,
        source_mime="application/pdf",
        source_filename=pdf.filename,
        target_format="png",
    )
    assert image.mime_type == "image/png"
    assert image.data.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_file_capability_owns_converted_asset_and_returns_file_result() -> None:
    source = _png()
    assets = Assets(source)
    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.FILE_CONVERT,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(None, None, "dm"),
        attachments=(
            AttachmentRef(
                "1",
                "https://cdn.example/input.png",
                "input.png",
                "image/png",
                len(source),
            ),
        ),
        options={"target": "jpg"},
    )

    result = await FileConvertCapability(
        assets,
        RawIngestor(assets.asset),
        LocalFileProcessor(),
    ).execute(request)

    assert isinstance(result, FileResult)
    assert result.filename == "input.jpg"
    assert result.asset.mime_type == "image/jpeg"
