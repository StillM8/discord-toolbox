from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from toolbox.capabilities.time import TimeConversionCapability
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    ErrorResult,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, 12, tzinfo=UTC)


def request(text: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.TIME,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        text=text,
    )


@pytest.mark.asyncio
async def test_time_conversion_uses_iana_zones() -> None:
    result = await TimeConversionCapability().execute(
        request("5pm America/New_York Asia/Karachi")
    )

    assert isinstance(result, TextResult)
    assert "Asia/Karachi" in result.text
    assert "17:00" in result.text


@pytest.mark.asyncio
async def test_time_conversion_rejects_unknown_zones() -> None:
    result = await TimeConversionCapability().execute(request("5pm Not/AZone Asia/Karachi"))

    assert isinstance(result, ErrorResult)
    assert result.code == "invalid_request"


@pytest.mark.asyncio
async def test_time_accepts_friendly_places_and_returns_current_times() -> None:
    result = await TimeConversionCapability(FixedClock()).execute(request("UK Islamabad"))

    assert isinstance(result, TextResult)
    assert "UK:" in result.text
    assert "Islamabad:" in result.text
    assert "12:00 GMT" in result.text
    assert "17:00 PKT" in result.text


@pytest.mark.asyncio
async def test_time_accepts_common_typos_and_place_names() -> None:
    result = await TimeConversionCapability(FixedClock()).execute(request("bradfort paksitan"))

    assert isinstance(result, TextResult)
    assert "Bradford:" in result.text
    assert "Pakistan:" in result.text


@pytest.mark.asyncio
async def test_time_accepts_friendly_places_for_explicit_conversion() -> None:
    result = await TimeConversionCapability(FixedClock()).execute(
        request("5pm UK Karachi")
    )

    assert isinstance(result, TextResult)
    assert "17:00 GMT" in result.text
    assert "22:00 PKT" in result.text
