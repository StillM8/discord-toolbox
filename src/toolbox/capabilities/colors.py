"""Small color inspection and palette helpers."""

from __future__ import annotations

import colorsys
import re
import secrets

from toolbox.core.actions import share_action
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class ColorCapability:
    """Inspect or complement common hex, RGB, and named colors."""

    _named: dict[str, tuple[int, int, int]] = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "green": (0, 128, 0),
        "blue": (0, 0, 255),
        "yellow": (255, 255, 0),
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
        "orange": (255, 165, 0),
        "purple": (128, 0, 128),
        "pink": (255, 192, 203),
        "gray": (128, 128, 128),
        "grey": (128, 128, 128),
    }
    _rgb = re.compile(r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$", re.I)

    async def execute(self, request: ToolRequest) -> ToolResult:
        mode = request.options.get("mode", "inspect").strip().lower()
        value = (request.text or request.options.get("value", "")).strip()
        if mode == "random":
            rgb = (
                secrets.randbelow(256),
                secrets.randbelow(256),
                secrets.randbelow(256),
            )
        else:
            try:
                rgb = self._parse(value)
            except InvalidRequest as error:
                return ErrorResult(
                    code=error.code,
                    message="Use a color such as `#5865F2`, `rgb(88,101,242)`, or `rebeccapurple`.",
                )
        if mode == "complement":
            rgb = (255 - rgb[0], 255 - rgb[1], 255 - rgb[2])
        elif mode not in {"inspect", "random"}:
            error = InvalidRequest
            return ErrorResult(code=error.code, message="Choose inspect, complement, or random.")
        text = self._describe(rgb)
        return TextResult(
            title=f"Color · {mode}",
            text=text,
            input_text=value or mode,
            actions=(share_action(),),
        )

    @classmethod
    def _parse(cls, value: str) -> tuple[int, int, int]:
        normalized = value.lower().strip()
        if normalized in cls._named:
            return cls._named[normalized]
        if normalized.startswith("#"):
            hex_value = normalized[1:]
            if len(hex_value) == 3:
                hex_value = "".join(char * 2 for char in hex_value)
            if len(hex_value) != 6 or not re.fullmatch(r"[0-9a-f]{6}", hex_value):
                raise InvalidRequest
            return (
                int(hex_value[0:2], 16),
                int(hex_value[2:4], 16),
                int(hex_value[4:6], 16),
            )
        match = cls._rgb.fullmatch(normalized)
        if match is None:
            raise InvalidRequest
        values = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        )
        if any(value > 255 for value in values):
            raise InvalidRequest
        return values

    @staticmethod
    def _describe(rgb: tuple[int, int, int]) -> str:
        red, green, blue = rgb
        hue, saturation, lightness = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        return (
            f"HEX: #{red:02X}{green:02X}{blue:02X}\n"
            f"RGB: {red}, {green}, {blue}\n"
            f"HSL: {round(hue * 360)}°, {round(saturation * 100)}%, {round(lightness * 100)}%"
        )
