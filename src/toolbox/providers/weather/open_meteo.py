"""Open-Meteo geocoding and current-weather adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import httpx

from toolbox.core.contracts import WeatherProvider
from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable
from toolbox.core.models import WeatherReport


class OpenMeteoWeatherProvider(WeatherProvider):
    """Use Open-Meteo without exposing its response format to the app."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search",
        forecast_url: str = "https://api.open-meteo.com/v1/forecast",
    ) -> None:
        self._client = client
        self._geocoding_url = geocoding_url
        self._forecast_url = forecast_url

    async def current(self, location: str) -> WeatherReport:
        if not location.strip() or len(location) > 200:
            raise InvalidRequest
        try:
            location_response = await self._client.get(
                self._geocoding_url,
                params={"name": location, "count": 1, "language": "en", "format": "json"},
            )
            location_response.raise_for_status()
            location_body = self._object(location_response.json())
            places = location_body.get("results")
            if not isinstance(places, list) or not places or not isinstance(places[0], dict):
                raise InvalidRequest
            place = cast(Mapping[str, object], places[0])
            latitude = self._float(place.get("latitude"))
            longitude = self._float(place.get("longitude"))
            name = str(place.get("name") or location)
            timezone = str(place.get("timezone") or "UTC")

            forecast_response = await self._client.get(
                self._forecast_url,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": (
                        "temperature_2m,relative_humidity_2m,apparent_temperature,"
                        "weather_code,wind_speed_10m"
                    ),
                    "timezone": "auto",
                },
            )
            forecast_response.raise_for_status()
            forecast_body = self._object(forecast_response.json())
            current = forecast_body.get("current")
            if not isinstance(current, dict):
                raise ProviderUnavailable
            current_data = cast(Mapping[str, object], current)
            return WeatherReport(
                location=name,
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
                temperature_c=self._float(current_data.get("temperature_2m")),
                feels_like_c=self._optional_float(current_data.get("apparent_temperature")),
                humidity_percent=self._optional_float(
                    current_data.get("relative_humidity_2m")
                ),
                wind_speed_kmh=self._optional_float(current_data.get("wind_speed_10m")),
                weather_code=self._optional_int(current_data.get("weather_code")),
            )
        except InvalidRequest:
            raise
        except httpx.TimeoutException as error:
            raise ProviderTimeout from error
        except httpx.HTTPError as error:
            raise ProviderUnavailable from error
        except (TypeError, ValueError, KeyError) as error:
            raise ProviderUnavailable from error

    @staticmethod
    def _object(value: object) -> Mapping[str, object]:
        if not isinstance(value, dict):
            raise ProviderUnavailable
        return cast(Mapping[str, object], value)

    @staticmethod
    def _float(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProviderUnavailable
        return float(value)

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value is None:
            return None
        return OpenMeteoWeatherProvider._float(value)

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProviderUnavailable
        return value
