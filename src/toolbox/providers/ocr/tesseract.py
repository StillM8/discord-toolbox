"""Optional local Tesseract OCR adapter."""

from __future__ import annotations

import asyncio
import io
from typing import Any, cast

import pytesseract  # pyright: ignore[reportMissingTypeStubs]
from PIL import Image

from toolbox.core.errors import ProviderUnavailable
from toolbox.core.models import OCRResult


class TesseractOCRProvider:
    """Run local Tesseract without blocking the async event loop."""

    async def extract(self, data: bytes, mime_type: str) -> OCRResult:
        if not data or not mime_type.startswith("image/"):
            raise ProviderUnavailable
        try:
            text = await asyncio.to_thread(self._extract, data)
        except (OSError, RuntimeError, pytesseract.TesseractNotFoundError) as error:
            raise ProviderUnavailable from error
        return OCRResult(text=text.strip())

    @staticmethod
    def _extract(data: bytes) -> str:
        with Image.open(io.BytesIO(data)) as image:
            return cast(
                str,
                pytesseract.image_to_string(  # pyright: ignore[reportUnknownMemberType]
                    cast(Any, image)
                ),
            )
