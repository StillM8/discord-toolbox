from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from toolbox.capabilities.convert import ConvertCapability
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    CurrencyQuote,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)
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
        assert request.url.path == "/latest"
        assert request.url.params["from"] == "USD"
        assert request.url.params["to"] == "PKR"
        return httpx.Response(200, json={"rates": {"PKR": 280.0}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        quote = await FrankfurterCurrencyProvider(client).convert(75, "USD", "PKR")
    finally:
        await client.aclose()

    assert quote.converted == 280.0
    assert quote.rate == 280.0 / 75


@pytest.mark.asyncio
async def test_convert_capability_routes_currency_without_ai() -> None:
    class Currency:
        async def convert(self, amount: float, base: str, target: str) -> CurrencyQuote:
            return CurrencyQuote(amount, base, target, 21_000.0, 280.0)

    result = await ConvertCapability(currency=Currency()).execute(request("75 USD PKR"))

    assert isinstance(result, TextResult)
    assert "21,000 PKR" in result.text
