from __future__ import annotations

import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from toolbox.capabilities.colors import ColorCapability
from toolbox.capabilities.encoding import EncodingCapability
from toolbox.capabilities.file_info import FileInfoCapability
from toolbox.capabilities.json_tools import JsonCapability
from toolbox.capabilities.random_tools import RandomCapability
from toolbox.capabilities.text_tools import TextCapability
from toolbox.capabilities.timestamp import TimestampCapability
from toolbox.core.models import (
    ActorContext,
    AttachmentRef,
    CapabilityName,
    ErrorResult,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)


def request(
    capability: CapabilityName,
    text: str = "",
    *,
    options: dict[str, str] | None = None,
    attachments: tuple[AttachmentRef, ...] = (),
) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=capability,
        actor=ActorContext(user=UserContext(user_id=1, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
        text=text,
        options=options or {},
        attachments=attachments,
    )


@pytest.mark.asyncio
async def test_random_capability_supports_dice_and_bounded_choices() -> None:
    capability = RandomCapability(random.Random(4))

    dice = await capability.execute(
        request(CapabilityName.RANDOM, "2d6", options={"mode": "dice"})
    )
    choice = await capability.execute(
        request(CapabilityName.RANDOM, "red | blue", options={"mode": "choose"})
    )

    assert isinstance(dice, TextResult)
    assert "Total:" in dice.text
    assert isinstance(choice, TextResult)
    assert choice.text in {"red", "blue"}


@pytest.mark.asyncio
async def test_random_password_is_not_shareable_by_default() -> None:
    result = await RandomCapability(random.Random(1)).execute(
        request(CapabilityName.RANDOM, "", options={"mode": "password", "value": "20"})
    )

    assert isinstance(result, TextResult)
    assert len(result.text) == 20
    assert result.actions == ()


@pytest.mark.asyncio
async def test_text_capability_counts_and_slugs() -> None:
    capability = TextCapability()
    counted = await capability.execute(
        request(CapabilityName.TEXT, "hello world\nagain", options={"mode": "count"})
    )
    slug = await capability.execute(
        request(CapabilityName.TEXT, "  Café & Toolbox!  ", options={"mode": "slug"})
    )

    assert isinstance(counted, TextResult)
    assert "Words: 3" in counted.text
    assert isinstance(slug, TextResult)
    assert slug.text == "cafe-toolbox"


@pytest.mark.asyncio
async def test_encoding_capability_round_trips_and_hashes() -> None:
    capability = EncodingCapability()
    encoded = await capability.execute(
        request(CapabilityName.ENCODE, "hello", options={"mode": "base64_encode"})
    )
    decoded = await capability.execute(
        request(CapabilityName.ENCODE, "aGVsbG8=", options={"mode": "base64_decode"})
    )
    hashed = await capability.execute(
        request(
            CapabilityName.ENCODE,
            "hello",
            options={"mode": "hash", "algorithm": "sha256"},
        )
    )

    assert isinstance(encoded, TextResult) and encoded.text == "aGVsbG8="
    assert isinstance(decoded, TextResult) and decoded.text == "hello"
    assert isinstance(hashed, TextResult)
    assert hashed.text == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


@pytest.mark.asyncio
async def test_json_capability_formats_and_rejects_invalid_json() -> None:
    capability = JsonCapability()
    formatted = await capability.execute(
        request(CapabilityName.JSON, '{"b":2,"a":1}', options={"mode": "sort"})
    )
    invalid = await capability.execute(
        request(CapabilityName.JSON, '{"broken":', options={"mode": "validate"})
    )

    assert isinstance(formatted, TextResult)
    assert formatted.text.index('"a"') < formatted.text.index('"b"')
    assert isinstance(invalid, ErrorResult)
    assert invalid.code == "invalid_json"


@pytest.mark.asyncio
async def test_color_capability_reports_and_complements_colors() -> None:
    capability = ColorCapability()
    inspected = await capability.execute(
        request(CapabilityName.COLOR, "#5865F2", options={"mode": "inspect"})
    )
    complement = await capability.execute(
        request(CapabilityName.COLOR, "#000000", options={"mode": "complement"})
    )

    assert isinstance(inspected, TextResult)
    assert "RGB: 88, 101, 242" in inspected.text
    assert isinstance(complement, TextResult)
    assert "#FFFFFF" in complement.text


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_timestamp_capability_returns_discord_ready_markup() -> None:
    capability = TimestampCapability(FixedClock())
    now = await capability.execute(
        request(CapabilityName.TIMESTAMP, options={"mode": "now", "timezone": "Asia/Karachi"})
    )
    parsed = await capability.execute(
        request(CapabilityName.TIMESTAMP, "1754827200", options={"mode": "unix"})
    )

    assert isinstance(now, TextResult)
    assert "17:00:00 PKT" in now.text
    assert isinstance(parsed, TextResult)
    assert "<t:1754827200:F>" in parsed.text


@pytest.mark.asyncio
async def test_file_info_is_read_only_and_uses_normalized_attachment_data() -> None:
    result = await FileInfoCapability().execute(
        request(
            CapabilityName.FILE_INFO,
            attachments=(
                AttachmentRef(
                    attachment_id="1",
                    source_url="https://cdn.discordapp.com/file.png",
                    filename="file.png",
                    declared_content_type="image/png",
                    declared_size=2_048,
                ),
            ),
        )
    )

    assert isinstance(result, TextResult)
    assert "file.png" in result.text
    assert "2.0 KiB" in result.text
