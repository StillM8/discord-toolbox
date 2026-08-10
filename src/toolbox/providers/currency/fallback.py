"""Composition helpers for replaceable currency providers."""

from __future__ import annotations

from toolbox.core.contracts import CurrencyProvider
from toolbox.core.errors import InvalidRequest, ProviderUnavailable, RateLimited
from toolbox.core.models import CurrencyQuote


class FallbackCurrencyProvider:
    """Use a secondary provider when the primary cannot answer a quote."""

    def __init__(
        self,
        *,
        primary: CurrencyProvider,
        fallback: CurrencyProvider,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
        try:
            return await self._primary.convert(amount, base, target)
        except (InvalidRequest, ProviderUnavailable, RateLimited):
            return await self._fallback.convert(amount, base, target)
