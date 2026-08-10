"""Codex built-in ImageGen adapter with a narrow image-provider contract."""

from __future__ import annotations

from typing import Protocol

from toolbox.core.contracts import ImageEditingProvider, ImageGenerationProvider
from toolbox.core.models import GeneratedImage, ImageEditRequest, ImageGenerationRequest


class CodexImageBackend(Protocol):
    """The public image surface exposed by the Codex provider implementation."""

    async def generate_image(self, request: ImageGenerationRequest) -> GeneratedImage:
        """Generate one image artifact through Codex."""

        ...

    async def edit_image(self, request: ImageEditRequest) -> GeneratedImage:
        """Edit one image artifact through Codex."""

        ...


class CodexImageProvider(ImageGenerationProvider, ImageEditingProvider):
    """Expose Codex ImageGen without leaking the Codex SDK into capabilities."""

    def __init__(self, backend: CodexImageBackend) -> None:
        self._backend = backend

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        return await self._backend.generate_image(request)

    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        return await self._backend.edit_image(request)
