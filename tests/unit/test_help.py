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
