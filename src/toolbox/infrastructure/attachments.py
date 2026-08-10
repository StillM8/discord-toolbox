"""Safe remote attachment ingestion into application-owned assets."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping

import httpx
import magic

from toolbox.core.contracts import AssetStore
from toolbox.core.errors import AssetRejected, ProviderTimeout, ProviderUnavailable
from toolbox.core.models import AssetRef, AttachmentRef
from toolbox.infrastructure.logging import log_event
from toolbox.infrastructure.media import ImageProcessor
from toolbox.infrastructure.url_policy import RemoteUrlPolicy

_logger = logging.getLogger("toolbox.attachments")


class AttachmentIngestor:
    """Download bounded image attachments, verify bytes, sanitize metadata, and store them."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        assets: AssetStore,
        *,
        max_bytes: int = 25 * 1024 * 1024,
        max_pixels: int = 20_000_000,
        processor: ImageProcessor | None = None,
        url_policy: RemoteUrlPolicy | None = None,
    ) -> None:
        self._client = client
        self._assets = assets
        self._max_bytes = max_bytes
        self._max_pixels = max_pixels
        self._processor = processor or ImageProcessor()
        self._url_policy = url_policy or RemoteUrlPolicy()

    async def ingest(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        started = time.perf_counter()
        data = await self._validated_download(attachment, owner_id)
        sanitized = await self._processor.transform(
            data,
            "sanitize",
            max_pixels=self._max_pixels,
        )
        asset = await self._assets.put(
            sanitized,
            owner_id=owner_id,
            mime_type="image/png",
            ttl_seconds=1_800,
        )
        log_event(
            _logger,
            "attachment_ingest_completed",
            attachment_id=attachment.attachment_id,
            owner_id=owner_id,
            downloaded_bytes=len(data),
            sanitized_bytes=len(sanitized),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return asset

    async def ingest_transformed(
        self,
        attachment: AttachmentRef,
        owner_id: int,
        *,
        operation: str,
        options: Mapping[str, str] | None = None,
    ) -> AssetRef:
        """Run one requested local image operation during attachment ingestion."""

        started = time.perf_counter()
        data = await self._validated_download(attachment, owner_id)
        transformed = await self._processor.transform(
            data,
            operation,
            options,
            max_pixels=self._max_pixels,
        )
        asset = await self._assets.put(
            transformed,
            owner_id=owner_id,
            mime_type="image/png",
            ttl_seconds=1_800,
        )
        log_event(
            _logger,
            "attachment_transform_completed",
            attachment_id=attachment.attachment_id,
            owner_id=owner_id,
            operation=operation,
            downloaded_bytes=len(data),
            transformed_bytes=len(transformed),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return asset

    async def ingest_raw(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
        """Store bounded audio/video/document bytes without image re-encoding."""

        data = await self._validated_download(attachment, owner_id)
        mime_type = self._sniff_mime(data, attachment.declared_content_type)
        return await self._assets.put(
            data,
            owner_id=owner_id,
            mime_type=mime_type,
            ttl_seconds=1_800,
        )

    async def _validated_download(self, attachment: AttachmentRef, owner_id: int) -> bytes:
        started = time.perf_counter()
        await self._url_policy.validate_network_target(attachment.source_url)
        log_event(
            _logger,
            "attachment_url_validated",
            attachment_id=attachment.attachment_id,
            owner_id=owner_id,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        if attachment.declared_size < 0 or attachment.declared_size > self._max_bytes:
            raise AssetRejected
        return await self._download(attachment.source_url)

    async def _download(self, url: str) -> bytes:
        started = time.perf_counter()
        chunks: list[bytes] = []
        total = 0
        try:
            async with self._client.stream("GET", url) as response:
                if response.status_code >= 400 or response.is_redirect:
                    raise ProviderUnavailable
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError as error:
                        raise AssetRejected from error
                    if declared_length > self._max_bytes:
                        raise AssetRejected
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self._max_bytes:
                        raise AssetRejected
                    chunks.append(chunk)
        except httpx.TimeoutException as error:
            raise ProviderTimeout from error
        except httpx.HTTPError as error:
            raise ProviderUnavailable from error
        data = b"".join(chunks)
        log_event(
            _logger,
            "attachment_download_completed",
            downloaded_bytes=len(data),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return data

    @staticmethod
    def _sniff_mime(data: bytes, declared: str | None) -> str:
        """Accept common signatures; extensions and declared MIME remain only hints."""

        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
            return "audio/wav"
        if data.startswith(b"OggS"):
            return "audio/ogg"
        if data.startswith(b"ID3") or (
            len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0
        ):
            return "audio/mpeg"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "audio/mp4" if (declared or "").startswith("audio/") else "video/mp4"
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm"
        if data.startswith(b"%PDF-"):
            return "application/pdf"
        detected = magic.from_buffer(data, mime=True).lower().split(";", 1)[0].strip()
        if detected in {
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "image/heic",
            "image/heif",
            "audio/wav",
            "audio/x-wav",
            "audio/ogg",
            "audio/mpeg",
            "audio/mp4",
            "video/mp4",
            "video/webm",
            "application/pdf",
        }:
            return "audio/wav" if detected == "audio/x-wav" else detected
        raise AssetRejected
