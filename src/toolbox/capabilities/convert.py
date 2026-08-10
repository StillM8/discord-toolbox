"""Deterministic unit conversion capability."""

from __future__ import annotations

import re
from typing import Any

from pint import DimensionalityError, UnitRegistry
from pint.errors import UndefinedUnitError

from toolbox.core.actions import share_action
from toolbox.core.contracts import CurrencyProvider
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class UnitConverter:
    """Convert common units through Pint without involving an AI provider."""

    _aliases = {
        "mm": "millimeter",
        "millimeters": "millimeter",
        "cm": "centimeter",
        "centimeters": "centimeter",
        "m": "meter",
        "meters": "meter",
        "km": "kilometer",
        "kilometers": "kilometer",
        "in": "inch",
        "inches": "inch",
        "ft": "foot",
        "feet": "foot",
        "yd": "yard",
        "yards": "yard",
        "mi": "mile",
        "miles": "mile",
        "g": "gram",
        "grams": "gram",
        "kg": "kilogram",
        "kilograms": "kilogram",
        "lb": "pound",
        "lbs": "pound",
        "pounds": "pound",
        "oz": "ounce",
        "ounces": "ounce",
        "b": "byte",
        "bytes": "byte",
        "kb": "kib",
        "mb": "mib",
        "gb": "gib",
        "tb": "tib",
        "mps": "meter / second",
        "m/s": "meter / second",
        "kph": "kilometer / hour",
        "kmh": "kilometer / hour",
        "km/h": "kilometer / hour",
        "mph": "mile / hour",
        "c": "degree_Celsius",
        "celsius": "degree_Celsius",
        "°c": "degree_Celsius",
        "degree_celsius": "degree_Celsius",
        "f": "degree_Fahrenheit",
        "fahrenheit": "degree_Fahrenheit",
        "°f": "degree_Fahrenheit",
        "degree_fahrenheit": "degree_Fahrenheit",
        "k": "kelvin",
    }

    _pattern = re.compile(
        r"^\s*(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
        r"(?P<source>[a-zA-Z/°]+)\s*(?:to\s*)?"
        r"(?P<target>[a-zA-Z/°]+)\s*$",
        re.IGNORECASE,
    )
    _height_pattern = re.compile(
        r"^\s*(?P<feet>[+-]?\d+(?:\.\d*)?)\s*(?:ft|feet|foot)\s*"
        r"(?P<inches>\d+(?:\.\d*)?)\s*(?:in|inch|inches)\s*"
        r"(?P<target>[a-zA-Z/°]+)\s*$",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self._registry: Any = UnitRegistry(autoconvert_offset_to_baseunit=True)
        self._registry.define("kib = 1024 * byte")
        self._registry.define("mib = 1024 * kib")
        self._registry.define("gib = 1024 * mib")
        self._registry.define("tib = 1024 * gib")

    def convert(self, expression: str) -> tuple[float, str, str]:
        """Convert ``value source target`` and return value/source/target."""

        height_match = self._height_pattern.match(expression)
        if height_match:
            inches = float(height_match.group("feet")) * 12 + float(height_match.group("inches"))
            source = "in"
            target = self._normalize(height_match.group("target"))
            return self._convert_value(inches, source, target), source, target

        match = self._pattern.match(expression)
        if not match:
            raise InvalidRequest
        value = float(match.group("value"))
        source = self._normalize(match.group("source"))
        target = self._normalize(match.group("target"))
        return self._convert_value(value, source, target), source, target

    def _convert_value(self, value: float, source: str, target: str) -> float:
        try:
            source_quantity: Any = self._registry.Quantity(value, self._normalize(source))
            converted: Any = source_quantity.to(self._normalize(target))
        except (
            DimensionalityError,
            UndefinedUnitError,
            ValueError,
            TypeError,
            AttributeError,
        ) as error:
            raise InvalidRequest from error
        return float(converted.magnitude)

    @staticmethod
    def _normalize(unit: str) -> str:
        normalized = unit.lower().strip()
        return UnitConverter._aliases.get(normalized, normalized)


class ConvertCapability:
    """Convert units and return a generic text result."""

    _currency_pattern = re.compile(
        r"^\s*(?P<amount>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+"
        r"(?P<base>[A-Za-z]{3})\s+(?:to\s+)?(?P<target>[A-Za-z]{3})\s*$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        converter: UnitConverter | None = None,
        currency: CurrencyProvider | None = None,
    ) -> None:
        self._converter = converter or UnitConverter()
        self._currency = currency

    async def execute(self, request: ToolRequest) -> ToolResult:
        expression = request.text or request.options.get("expression", "")
        try:
            value, _, target = self._converter.convert(expression)
        except InvalidRequest:
            currency_request = self._parse_currency(expression)
            if currency_request is None or self._currency is None:
                error = InvalidRequest
                return ErrorResult(
                    code=error.code,
                    message="Use units like `5 ft 11 in cm` or currencies like `75 USD PKR`.",
                )
            amount, base, target_currency = currency_request
            try:
                quote = await self._currency.convert(amount, base, target_currency)
            except ToolboxError as error:
                return ErrorResult(
                    code=error.code,
                    message=error.user_message,
                    retryable=error.retryable,
                )
            return TextResult(
                title="Currency conversion",
                text=(
                    f"{self._format(quote.amount)} {quote.base} ≈ "
                    f"{self._format(quote.converted)} {quote.target}\n"
                    f"Rate: {quote.rate:.8g}"
                ),
                input_text=expression.strip(),
                actions=(share_action(),),
            )
        return TextResult(
            title="Conversion",
            text=f"{self._format(value)} {target} (from {expression.strip()})",
            input_text=expression.strip(),
            actions=(share_action(),),
        )

    @classmethod
    def _parse_currency(cls, expression: str) -> tuple[float, str, str] | None:
        match = cls._currency_pattern.match(expression)
        if match is None:
            return None
        return (
            float(match.group("amount")),
            match.group("base").upper(),
            match.group("target").upper(),
        )

    @staticmethod
    def _format(value: float) -> str:
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.8g}"
