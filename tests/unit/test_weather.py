from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
import respx

from toolbox.capabilities.weather import WeatherCapability
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.providers.weather.open_meteo import OpenMeteoWeatherProvider


def request(text: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.WEATHER,
        actor=ActorContext(user=UserContext(user_id=1, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        text=text,
    )


@pytest.mark.asyncio
@respx.mock
async def test_open_meteo_is_normalized_before_weather_capability() -> None:
    respx.get("https://geo.test/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Islamabad",
                        "latitude": 33.7,
                        "longitude": 73.1,
                        "timezone": "Asia/Karachi",
                    }
                ]
            },
        )
    )
    respx.get("https://forecast.test/current").mock(
        return_value=httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 31.2,
                    "relative_humidity_2m": 45,
                    "apparent_temperature": 34.0,
                    "weather_code": 2,
                    "wind_speed_10m": 12.5,
                }
            },
        )
    )
    async with httpx.AsyncClient() as client:
        provider = OpenMeteoWeatherProvider(
            client,
            geocoding_url="https://geo.test/search",
            forecast_url="https://forecast.test/current",
        )
        result = await WeatherCapability(provider).execute(request("Islamabad"))

    assert isinstance(result, TextResult)
    assert "31.2°C" in result.text
    assert "Partly cloudy" in result.text
    assert result.actions


@pytest.mark.asyncio
async def test_weather_rejects_empty_location() -> None:
    class Provider:
        async def current(self, location: str):
            raise AssertionError(location)

    result = await WeatherCapability(Provider()).execute(request(""))

    assert result.code == "invalid_request"  # type: ignore[attr-defined]
