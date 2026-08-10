from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from toolbox.app.bootstrap import build_runtime
from toolbox.config.settings import Settings
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)


@pytest.mark.asyncio
async def test_composition_root_builds_and_closes_current_runtime(tmp_path: Path) -> None:
    settings = Settings(
        discord_token=SecretStr("test-token"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'toolbox.sqlite3'}",
        asset_directory=tmp_path / "assets",
    )
    runtime = build_runtime(settings)

    await runtime.start()
    async with runtime.database.engine.connect() as connection:
        migration = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        fts_table = await connection.scalar(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'saved_items_fts'"
            )
        )
    assert migration == "0005_accessibility_preferences"
    assert fts_table == "saved_items_fts"
    result = await runtime.dispatcher.execute(
        ToolRequest(
            request_id=uuid4(),
            capability=CapabilityName.CALCULATE,
            actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
            interaction=InteractionContext(
                guild_id=None,
                channel_id=None,
                surface="test",
            ),
            text="2 + 2",
        )
    )

    assert isinstance(result, TextResult)
    assert result.text == "4"
    assert (tmp_path / "assets").is_dir()
    await runtime.close()
