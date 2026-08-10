"""Keyless exchange-rate adapter for currencies outside Frankfurter's set."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

import httpx

from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import CurrencyQuote


class ExchangeRateApiCurrencyProvider:
    """Use ExchangeRate-API's public latest-rates endpoint behind a narrow contract.

    This is a fallback for currencies that are not represented by Frankfurter's
    ECB-based dataset.  It deliberately returns the same neutral ``CurrencyQuote``
    as the primary adapter and never exposes the provider response upstream.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://open.er-api.com/v6/latest",
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
        base = base.upper()
        target = target.upper()
        if (
            not math.isfinite(amount)
            or amount < -1e15
            or amount > 1e15
            or len(base) != 3
            or len(target) != 3
        ):
            raise InvalidRequest
        if base == target:
            return CurrencyQuote(amount, base, target, amount, 1.0)

        try:
            response = await self._client.get(f"{self._base_url}/{base}")
        except httpx.TimeoutException as error:
            raise ProviderTimeout from error
        except httpx.HTTPError as error:
            raise ProviderUnavailable from error

        if response.status_code == 429:
            raise RateLimited
        if response.status_code >= 500:
            raise ProviderUnavailable
        if response.status_code >= 400:
            raise InvalidRequest

        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("invalid response")
            body_map = cast(Mapping[str, object], body)
            if body_map.get("result") != "success":
                raise ValueError("unsuccessful response")
            raw_rates = body_map.get("rates")
            if not isinstance(raw_rates, Mapping):
                raise ValueError("invalid rates")
            rates = cast(Mapping[str, object], raw_rates)
            raw_rate = rates.get(target)
            if isinstance(raw_rate, bool) or not isinstance(raw_rate, (int, float, str)):
                raise ValueError("missing target rate")
            rate = float(raw_rate)
            if not math.isfinite(rate) or rate <= 0:
                raise ValueError("invalid target rate")
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable from error

        return CurrencyQuote(
            amount=amount,
            base=base,
            target=target,
            converted=amount * rate,
            rate=rate,
        )
