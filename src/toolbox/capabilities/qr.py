"""Local QR-code generation capability."""

from __future__ import annotations

import asyncio
import io

import qrcode

from toolbox.core.actions import share_action
from toolbox.core.contracts import AssetStore
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, ImageResult, ToolRequest, ToolResult


class QRCapability:
    """Generate a QR image locally and place it in the application asset store."""

    def __init__(self, assets: AssetStore) -> None:
        self._assets = assets

    async def execute(self, request: ToolRequest) -> ToolResult:
        value = (request.text or request.options.get("value", "")).strip()
        if not value or len(value) > 2_000:
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message="Give me a URL or text up to 2,000 characters.",
            )

        data = await asyncio.to_thread(self._encode, value)
        asset = await self._assets.put(
            data,
            owner_id=request.actor.user.user_id,
            mime_type="image/png",
            ttl_seconds=86_400,
        )
        return ImageResult(
            asset=asset,
            title="QR code",
            input_text=value,
            actions=(share_action(),),
        )

    @staticmethod
    def _encode(value: str) -> bytes:
        image = qrcode.make(value)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()
