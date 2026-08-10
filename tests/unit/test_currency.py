from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from toolbox.capabilities.convert import ConvertCapability
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    CurrencyQuote,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.providers.currency.exchange_rate_api import ExchangeRateApiCurrencyProvider
from toolbox.providers.currency.fallback import FallbackCurrencyProvider
from toolbox.providers.currency.frankfurter import FrankfurterCurrencyProvider


def request(text: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.CONVERT,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        text=text,
    )


@pytest.mark.asyncio
async def test_currency_provider_normalizes_exchange_rate_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.frankfurter.dev"
        assert request.url.path == "/v1/latest"
        assert request.url.params["from"] == "USD"
        assert request.url.params["to"] == "EUR"
        return httpx.Response(200, json={"rates": {"EUR": 64.875}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        quote = await FrankfurterCurrencyProvider(client).convert(75, "USD", "EUR")
    finally:
        await client.aclose()

    assert quote.converted == 64.875
    assert quote.rate == 64.875 / 75


@pytest.mark.asyncio
async def test_convert_capability_routes_currency_without_ai() -> None:
    class Currency:
        async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
            return CurrencyQuote(amount, base, target, 21_000.0, 280.0)

    result = await ConvertCapability(currency=Currency()).execute(request("75 USD PKR"))

    assert isinstance(result, TextResult)
    assert "21,000 PKR" in result.text


@pytest.mark.asyncio
async def test_exchange_rate_api_provider_supports_currencies_outside_frankfurter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "open.er-api.com"
        assert request.url.path == "/v6/latest/USD"
        return httpx.Response(
            200,
            json={"result": "success", "rates": {"PKR": 277.9638}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        quote = await ExchangeRateApiCurrencyProvider(client).convert(75, "USD", "PKR")
    finally:
        await client.aclose()

    assert quote.converted == pytest.approx(20_847.285)
    assert quote.rate == pytest.approx(277.9638)


@pytest.mark.asyncio
async def test_currency_fallback_uses_secondary_provider_when_primary_cannot_answer() -> None:
    class FailingPrimary:
        async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
            raise InvalidRequest

    class Fallback:
        async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
            return CurrencyQuote(amount, base, target, 20_847.285, 277.9638)

    result = await FallbackCurrencyProvider(
        primary=FailingPrimary(),
        fallback=Fallback(),
    ).convert(75, "USD", "PKR")

    assert result.target == "PKR"
    assert result.converted == pytest.approx(20_847.285)
