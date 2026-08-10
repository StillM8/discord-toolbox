"""Current-weather capability backed by a replaceable weather provider."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import WeatherProvider
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class WeatherCapability:
    """Look up current conditions and return a shareable application result."""

    def __init__(self, provider: WeatherProvider) -> None:
        self._provider = provider

    async def execute(self, request: ToolRequest) -> ToolResult:
        location = (request.text or request.options.get("location", "")).strip()
        if not location or len(location) > 200:
            error = InvalidRequest
            return ErrorResult(code=error.code, message="Tell me which location to check.")
        try:
            report = await self._provider.current(location)
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        description = self._description(report.weather_code)
        lines = [
            f"{report.location} · {description}",
            f"Temperature: {report.temperature_c:.1f}°C",
        ]
        if report.feels_like_c is not None:
            lines.append(f"Feels like: {report.feels_like_c:.1f}°C")
        if report.humidity_percent is not None:
            lines.append(f"Humidity: {report.humidity_percent:.0f}%")
        if report.wind_speed_kmh is not None:
            lines.append(f"Wind: {report.wind_speed_kmh:.1f} km/h")
        lines.append(f"Timezone: {report.timezone}")
        return TextResult(
            title="Weather",
            text="\n".join(lines),
            input_text=location,
            actions=(share_action(),),
        )

    @staticmethod
    def _description(code: int | None) -> str:
        descriptions: dict[int, str] = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Foggy",
            48: "Rime fog",
            51: "Light drizzle",
            53: "Drizzle",
            55: "Heavy drizzle",
            61: "Light rain",
            63: "Rain",
            65: "Heavy rain",
            71: "Light snow",
            73: "Snow",
            75: "Heavy snow",
            80: "Rain showers",
            81: "Rain showers",
            82: "Heavy rain showers",
            95: "Thunderstorm",
            96: "Thunderstorm with hail",
            99: "Thunderstorm with heavy hail",
        }
        if code is None:
            return "Conditions unavailable"
        return descriptions.get(code, "Conditions unavailable")
