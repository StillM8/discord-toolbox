from __future__ import annotations

from uuid import uuid4

import pytest

from toolbox.capabilities.help import HelpCapability
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    HelpResult,
    InteractionContext,
    ToolRequest,
    UserContext,
)


@pytest.mark.asyncio
async def test_help_lists_search_alias_and_command_groups() -> None:
    result = await HelpCapability().execute(
        ToolRequest(
            request_id=uuid4(),
            capability=CapabilityName.HELP,
            actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
            interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
        )
    )

    assert isinstance(result, HelpResult)
    help_text = "\n".join(line for section in result.sections for line in section.lines)
    assert "`/help`" in help_text
    assert "`/toolbox`" in help_text
    assert "`/ping`" in help_text
    assert "`/search <query> [mode]`" in help_text
    assert "`/find <query> [mode]` — Alias for `/search`." in help_text
    assert "`/me codex-login`" in help_text
    assert "`/create image <prompt>`" in help_text
    assert "`/tool calc <expression>`" in help_text
    assert "Apps → Toolbox" in help_text
    assert "`/tool background <attachment>`" in help_text
    assert "`/me context`" in help_text
    assert "`/me accessibility`" in help_text


@pytest.mark.asyncio
async def test_help_mentions_every_current_slash_command_leaf() -> None:
    result = await HelpCapability().execute(
        ToolRequest(
            request_id=uuid4(),
            capability=CapabilityName.HELP,
            actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
            interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
        )
    )

    assert isinstance(result, HelpResult)
    help_text = "\n".join(line for section in result.sections for line in section.lines)
    command_names = (
        "ping",
        "help",
        "toolbox",
        "find",
        "search",
        "ask",
        "translate",
        "what",
        "research",
        "factcheck",
        "link",
        "time",
        "remind",
        "reminders",
        "cancel-reminder",
        "saved",
        "save",
        "bookmark",
        "bookmarks",
        "send-saved",
        "export-bookmarks",
        "unsave",
        "me preferences",
        "me accessibility",
        "me status",
        "me codex-login",
        "me saved",
        "me bookmarks",
        "me export",
        "me reminders",
        "me context",
        "create image",
        "create edit",
        "create meme",
        "create caption",
        "create quote",
        "create qr",
        "tool random",
        "tool text",
        "tool encode",
        "tool json",
        "tool color",
        "tool timestamp",
        "tool image",
        "tool fileinfo",
        "tool calc",
        "tool convert",
        "tool qr",
        "tool emoji",
        "tool time",
        "tool weather",
        "tool ocr",
        "tool transcribe",
        "tool background",
        "tool file",
    )
    missing = tuple(name for name in command_names if f"`/{name}" not in help_text)
    assert missing == ()
