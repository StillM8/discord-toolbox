"""Provider-backed image editing over explicitly selected assets."""

from __future__ import annotations

import re

from toolbox.core.actions import share_action
from toolbox.core.contracts import (
    AssetStore,
    AttachmentIngestor,
    ImageEditingProvider,
    ImageProcessor,
)
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AssetRef,
    ErrorResult,
    ImageEditRequest,
    ImageResult,
    ToolRequest,
    ToolResult,
)


class ImageEditCapability:
    """Edit one selected image and store the returned bytes as a transient asset.

    Explicitly deterministic edit requests use the local image processor. This
    keeps common utility-bot operations fast while preserving Codex for edits
    that actually require semantic image understanding.
    """

    def __init__(
        self,
        provider: ImageEditingProvider,
        assets: AssetStore,
        ingestor: AttachmentIngestor | None = None,
        local_processor: ImageProcessor | None = None,
    ) -> None:
        self._provider = provider
        self._assets = assets
        self._ingestor = ingestor
        self._local_processor = local_processor

    async def execute(self, request: ToolRequest) -> ToolResult:
        prompt = (request.text or request.options.get("prompt", "")).strip()
        if not prompt:
            prompt = "Improve this image while preserving its main subject."
        if len(prompt) > 2_000:
            error = InvalidRequest
            return ErrorResult(code=error.code, message="Keep the image edit instruction short.")
        try:
            source = await self._source_asset(request)
            fast_edit = _fast_edit_operation(prompt)
            if fast_edit is not None and self._local_processor is not None:
                operation, options = fast_edit
                transformed = await self._local_processor.transform(
                    await self._assets.read(source),
                    operation,
                    options,
                )
                asset = await self._assets.put(
                    transformed,
                    owner_id=request.actor.user.user_id,
                    mime_type="image/png",
                    ttl_seconds=86_400,
                )
                title = f"Quick edit · {operation}"
            else:
                generated = await self._provider.edit(
                    ImageEditRequest(asset=source, prompt=prompt)
                )
                asset = await self._assets.put(
                    generated.data,
                    owner_id=request.actor.user.user_id,
                    mime_type=generated.mime_type,
                    ttl_seconds=86_400,
                )
                title = "Edited image"
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="Select a supported image first.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        return ImageResult(
            asset=asset,
            title=title,
            input_text=prompt,
            actions=(share_action(),),
        )

    async def _source_asset(self, request: ToolRequest) -> AssetRef:
        for item in request.context_items:
            if item.asset is not None:
                return item.asset
        if request.target_message is not None and request.target_message.attachments:
            if self._ingestor is None:
                raise InvalidRequest
            return await self._ingestor.ingest(
                request.target_message.attachments[0],
                request.actor.user.user_id,
            )
        if request.attachments:
            if self._ingestor is None:
                raise InvalidRequest
            return await self._ingestor.ingest(request.attachments[0], request.actor.user.user_id)
        raise InvalidRequest


def _fast_edit_operation(prompt: str) -> tuple[str, dict[str, str]] | None:
    """Recognize safe, whole-image operations that do not need an AI model."""

    normalized = re.sub(r"[^a-z0-9]+", " ", prompt.casefold()).strip()
    if normalized in {
        "black and white",
        "make it black and white",
        "make this black and white",
        "convert to black and white",
        "grayscale",
        "greyscale",
        "make it grayscale",
        "make it greyscale",
    }:
        return "grayscale", {}
    if normalized in {
        "deep fry",
        "deep fried",
        "deepfry",
        "make it deep fried",
        "make this deep fried",
    }:
        return "deepfry", {}
    if normalized in {"blur", "blur it", "blur the image", "blur everything"}:
        return "blur", {}
    if normalized in {"pixelate", "pixelated", "pixelate it", "make it pixelated"}:
        return "pixelate", {}
    if normalized in {"mirror", "mirror it", "flip horizontally", "flip it"}:
        return "mirror", {}
    if normalized in {"rotate left", "turn left", "rotate counterclockwise"}:
        return "rotate", {"degrees": "-90"}
    if normalized in {"rotate right", "turn right", "rotate clockwise"}:
        return "rotate", {"degrees": "90"}
    return None
