from __future__ import annotations

from uuid import uuid4

import pytest

from toolbox.capabilities.calculate import CalculateCapability, SafeCalculator
from toolbox.capabilities.convert import ConvertCapability, UnitConverter
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)


def request(capability: CapabilityName, text: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=1, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
        text=text,
    )


def test_calculator_accepts_arithmetic() -> None:
    assert SafeCalculator().evaluate("(27 * 412) + 19") == 11_143


@pytest.mark.parametrize("expression", ["__import__('os')", "open('x')", "1 / 0", "2 ** 101"])
def test_calculator_rejects_code_and_unsafe_operations(expression: str) -> None:
    with pytest.raises(Exception):
        SafeCalculator().evaluate(expression)


@pytest.mark.asyncio
async def test_calculate_capability_returns_generic_text_result() -> None:
    result = await CalculateCapability().execute(request(CapabilityName.CALCULATE, "2 + 2"))

    assert isinstance(result, TextResult)
    assert result.text == "4"


def test_unit_converter_handles_height_and_speed() -> None:
    converter = UnitConverter()

    height, _, _ = converter.convert("5 ft 11 in cm")
    speed, _, _ = converter.convert("180 kmh mph")

    assert height == pytest.approx(180.34)
    assert speed == pytest.approx(111.8468, rel=1e-4)


@pytest.mark.asyncio
async def test_convert_capability_returns_generic_text_result() -> None:
    result = await ConvertCapability().execute(request(CapabilityName.CONVERT, "70 f c"))

    assert isinstance(result, TextResult)
    assert "21" in result.text
