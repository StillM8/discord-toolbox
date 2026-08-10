"""Disabled optional background-removal provider."""

from __future__ import annotations

from toolbox.core.errors import FeatureDisabled
from toolbox.core.models import GeneratedImage


class UnavailableBackgroundRemovalProvider:
    """Keep the capability registered while local ML is disabled."""

    async def remove(self, data: bytes, mime_type: str) -> GeneratedImage:
        del data, mime_type
        raise FeatureDisabled
