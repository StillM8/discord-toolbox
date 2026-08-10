"""Bounded local image, PDF, audio, and video conversion."""

from __future__ import annotations

import asyncio
import io
import mimetypes
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast

import pymupdf  # pyright: ignore[reportMissingTypeStubs]
from PIL import Image, ImageOps

from toolbox.core.errors import AssetRejected, ProviderTimeout, ProviderUnavailable
from toolbox.core.models import GeneratedFile


class LocalFileProcessor:
    """Use local libraries and a constrained ffmpeg subprocess for conversion."""

    def __init__(self, *, max_bytes: int = 25 * 1024 * 1024, timeout_seconds: float = 60.0) -> None:
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds

    async def convert(
        self,
        data: bytes,
        *,
        source_mime: str,
        source_filename: str,
        target_format: str,
    ) -> GeneratedFile:
        if not data or len(data) > self._max_bytes:
            raise AssetRejected
        target = target_format.lower().lstrip(".")
        stem = Path(source_filename).stem or "toolbox-file"
        if source_mime.startswith("image/"):
            return await asyncio.to_thread(self._image, data, stem, target)
        if source_mime == "application/pdf" and target in {"png", "jpg", "jpeg", "webp"}:
            return await asyncio.to_thread(self._pdf_page, data, stem, target)
        if (source_mime.startswith("audio/") or source_mime.startswith("video/")) and target in {
            "gif",
            "mp3",
            "wav",
            "mp4",
        }:
            return await self._ffmpeg(data, source_mime, stem, target)
        raise AssetRejected

    def _image(self, data: bytes, stem: str, target: str) -> GeneratedFile:
        formats = {
            "jpg": ("JPEG", "image/jpeg"),
            "jpeg": ("JPEG", "image/jpeg"),
            "pdf": ("PDF", "application/pdf"),
        }
        image_format, mime_type = formats.get(target, (target.upper(), f"image/{target}"))
        if image_format not in {"PNG", "JPEG", "WEBP", "GIF", "PDF"}:
            raise AssetRejected
        try:
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                if source.width * source.height > 20_000_000:
                    raise AssetRejected
                image = ImageOps.exif_transpose(source)
                if image_format in {"JPEG", "PDF"}:
                    image = image.convert("RGB")
                else:
                    image = image.convert("RGBA")
                output = io.BytesIO()
                save_kwargs: dict[str, object] = {}
                if image_format == "JPEG":
                    save_kwargs = {"quality": 90, "optimize": True}
                elif image_format == "PNG":
                    save_kwargs = {"optimize": True}
                image.save(output, format=image_format, **save_kwargs)
        except (AssetRejected, OSError, ValueError) as error:
            if isinstance(error, AssetRejected):
                raise
            raise AssetRejected from error
        result = output.getvalue()
        self._check_size(result)
        extension = "jpg" if image_format == "JPEG" else target
        return GeneratedFile(result, mime_type, f"{stem}.{extension}")

    def _pdf_page(self, data: bytes, stem: str, target: str) -> GeneratedFile:
        fitz_module = cast(Any, pymupdf)
        document: Any = None
        try:
            document = fitz_module.open(stream=data, filetype="pdf")
            if document.page_count < 1:
                raise AssetRejected
            page = document.load_page(0)
            pixmap = page.get_pixmap(matrix=fitz_module.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            output = io.BytesIO()
            image_format = "JPEG" if target in {"jpg", "jpeg"} else target.upper()
            save_kwargs: dict[str, object] = (
                {"quality": 90} if image_format == "JPEG" else {}
            )
            image.save(output, format=image_format, **save_kwargs)
        except (AssetRejected, OSError, ValueError, RuntimeError) as error:
            if isinstance(error, AssetRejected):
                raise
            raise AssetRejected from error
        finally:
            if document is not None:
                document.close()
        result = output.getvalue()
        self._check_size(result)
        extension = "jpg" if image_format == "JPEG" else target
        mime_type = "image/jpeg" if extension == "jpg" else f"image/{extension}"
        return GeneratedFile(result, mime_type, f"{stem}.{extension}")

    async def _ffmpeg(self, data: bytes, source_mime: str, stem: str, target: str) -> GeneratedFile:
        if shutil.which("ffmpeg") is None:
            raise ProviderUnavailable
        source_suffix = mimetypes.guess_extension(source_mime) or ".bin"
        output_suffix = f".{target}"
        try:
            with tempfile.TemporaryDirectory(prefix="toolbox-convert-") as directory:
                source = Path(directory) / f"input{source_suffix}"
                output = Path(directory) / f"output{output_suffix}"
                await asyncio.to_thread(source.write_bytes, data)
                process = await asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    str(output),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    _, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self._timeout_seconds,
                    )
                except TimeoutError as error:
                    process.kill()
                    await process.communicate()
                    raise ProviderTimeout from error
                if process.returncode != 0 or not output.is_file():
                    del stderr
                    raise AssetRejected
                result = await asyncio.to_thread(output.read_bytes)
        except FileNotFoundError as error:
            raise ProviderUnavailable from error
        self._check_size(result)
        mime_type = {
            "gif": "image/gif",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "mp4": "video/mp4",
        }[target]
        return GeneratedFile(result, mime_type, f"{stem}.{target}")

    def _check_size(self, data: bytes) -> None:
        if len(data) > self._max_bytes:
            raise AssetRejected
