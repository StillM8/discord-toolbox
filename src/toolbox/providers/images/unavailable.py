"""Explicit disabled-provider adapter used when optional credentials are absent."""

from __future__ import annotations

from toolbox.core.contracts import ImageEditingProvider, ImageGenerationProvider
from toolbox.core.errors import ProviderUnavailable
from toolbox.core.models import GeneratedImage, ImageEditRequest, ImageGenerationRequest


class UnavailableImageGenerationProvider(ImageGenerationProvider, ImageEditingProvider):
    """Keep the command registered while returning a safe configuration error."""

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        del request
        raise ProviderUnavailable

    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        del request
        raise ProviderUnavailable
