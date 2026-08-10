"""Explicit unavailable search providers for optional capabilities."""

from __future__ import annotations

from toolbox.core.errors import FeatureDisabled
from toolbox.core.models import SearchPage, SearchRequest


class UnavailableGifSearchProvider:
    """Keep optional GIF search registered without pretending it is configured."""

    async def search(self, request: SearchRequest) -> SearchPage:
        del request
        raise FeatureDisabled
