"""Primary/fallback routing for image generation and editing."""

from __future__ import annotations

from typing import cast

from toolbox.core.contracts import ImageEditingProvider, ImageGenerationProvider
from toolbox.core.errors import ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import GeneratedImage, ImageEditRequest, ImageGenerationRequest


class ImageProviderRouter(ImageGenerationProvider, ImageEditingProvider):
    """Try Codex first and use a configured fallback only for transient failures."""

    def __init__(
        self,
        primary: ImageGenerationProvider,
        fallback: ImageGenerationProvider | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        try:
            return await self._primary.generate(request)
        except (ProviderUnavailable, ProviderTimeout, RateLimited):
            if self._fallback is None:
                raise
            return await self._fallback.generate(request)

    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        primary = self._as_editor(self._primary)
        try:
            return await primary.edit(request)
        except (ProviderUnavailable, ProviderTimeout, RateLimited):
            if self._fallback is None:
                raise
            return await self._as_editor(self._fallback).edit(request)

    @staticmethod
    def _as_editor(provider: ImageGenerationProvider) -> ImageEditingProvider:
        if not hasattr(provider, "edit"):
            raise ProviderUnavailable
        return cast(ImageEditingProvider, provider)
