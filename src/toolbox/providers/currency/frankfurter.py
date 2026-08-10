"""Frankfurter exchange-rate adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import httpx

from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import CurrencyQuote


class FrankfurterCurrencyProvider:
    """Use Frankfurter's public latest-rates endpoint behind a narrow contract."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://api.frankfurter.app",
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
        base = base.upper()
        target = target.upper()
        if amount < -1e15 or amount > 1e15 or len(base) != 3 or len(target) != 3:
            raise InvalidRequest
        if base == target:
            return CurrencyQuote(amount, base, target, amount, 1.0)
        try:
            response = await self._client.get(
                f"{self._base_url}/latest",
                params={"amount": amount, "from": base, "to": target},
            )
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
            raw_rates = body_map.get("rates")
            if not isinstance(raw_rates, Mapping):
                raise ValueError("invalid rates")
            rates = cast(Mapping[str, object], raw_rates)
            raw_converted = rates.get(target)
            if isinstance(raw_converted, bool) or not isinstance(
                raw_converted,
                (int, float, str),
            ):
                raise ValueError("missing target rate")
            converted = float(raw_converted)
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable from error
        return CurrencyQuote(
            amount=amount,
            base=base,
            target=target,
            converted=converted,
            rate=converted / amount if amount else 0.0,
        )
