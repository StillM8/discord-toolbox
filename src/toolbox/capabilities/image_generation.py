"""User-requested image generation capability."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import AssetStore, ImageGenerationProvider
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    ErrorResult,
    ImageGenerationRequest,
    ImageResult,
    ToolRequest,
    ToolResult,
)


class ImageGenerationCapability:
    """Generate an image through a provider, then immediately own it as an asset."""

    def __init__(self, provider: ImageGenerationProvider, assets: AssetStore) -> None:
        self._provider = provider
        self._assets = assets

    async def execute(self, request: ToolRequest) -> ToolResult:
        prompt = (request.text or request.options.get("prompt", "")).strip()
        if not prompt or len(prompt) > 8_000:
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message="Give me an image prompt up to 8,000 characters.",
            )
        try:
            generated = await self._provider.generate(ImageGenerationRequest(prompt=prompt))
            asset = await self._assets.put(
                generated.data,
                owner_id=request.actor.user.user_id,
                mime_type=generated.mime_type,
                ttl_seconds=86_400,
            )
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return ImageResult(
            asset=asset,
            title="Generated image",
            input_text=prompt,
            actions=(share_action(),),
        )
