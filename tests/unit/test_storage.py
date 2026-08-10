from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from toolbox.core.models import (
    ActionKind,
    ContextItem,
    InteractionSession,
    MessageContext,
    QuoteColorMode,
    QuoteFont,
    QuoteImageMode,
    QuoteTextPosition,
    Reminder,
    ReminderStatus,
    SavedItem,
    SavedItemKind,
    UserPreferences,
)
from toolbox.infrastructure.clock import SystemClock
from toolbox.storage.database import Database
from toolbox.storage.repositories.context import SQLContextStore
from toolbox.storage.repositories.preferences import SQLPreferencesRepository
from toolbox.storage.repositories.reminders import SQLReminderRepository
from toolbox.storage.repositories.saved import SQLSavedItemRepository
from toolbox.storage.repositories.sessions import SQLSessionStore


@pytest.fixture
async def database(tmp_path: Path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_schema()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_context_saved_preferences_and_sessions_are_owner_scoped(database: Database) -> None:
    owner = 42
    context = SQLContextStore(database, SystemClock())
    item = ContextItem(
        item_id=uuid4(),
        owner_id=owner,
        label="message",
        message=MessageContext(
            message_id=1,
            author_id=2,
            author_name="Author",
            content="selected",
            channel_id=3,
            guild_id=4,
            reply_to_message_id=None,
        ),
    )
    await context.add(item)
    listed = await context.list(owner)

    saved = SQLSavedItemRepository(database)
    saved_item = SavedItem(
        item_id=uuid4(),
        owner_id=owner,
        kind=SavedItemKind.TEXT,
        title="Saved",
        text="selected",
        source_url=None,
        asset_id=None,
        created_at=datetime.now(UTC),
        tags=("idea", "selected"),
    )
    await saved.save(saved_item)

    preferences = SQLPreferencesRepository(database)
    await preferences.save(
        UserPreferences(
            owner_id=owner,
            timezone="Asia/Karachi",
            quote_font=QuoteFont.SERIF,
            quote_text_position=QuoteTextPosition.RIGHT,
            quote_color_mode=QuoteColorMode.COLOR,
            quote_image_mode=QuoteImageMode.BACKGROUND,
            accessibility_plain_text=True,
            accessibility_high_contrast=True,
            accessibility_reduce_motion=True,
            accessibility_verbose=True,
        )
    )

    sessions = SQLSessionStore(database, SystemClock())
    session = InteractionSession(
        session_id=uuid4(),
        owner_id=owner,
        action=ActionKind.SHARE,
        target_id=None,
        payload={"text": "selected"},
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await sessions.create(session)

    assert listed[0].message is not None
    assert listed[0].message.content == "selected"
    assert (await saved.search(owner, "selected"))[0].item_id == saved_item.item_id
    assert (await saved.search(owner, "idea"))[0].tags == ("idea", "selected")
    assert await saved.get(owner, saved_item.item_id) == saved_item
    assert (await preferences.get(owner)).timezone == "Asia/Karachi"
    loaded_preferences = await preferences.get(owner)
    assert loaded_preferences.quote_font is QuoteFont.SERIF
    assert loaded_preferences.quote_text_position is QuoteTextPosition.RIGHT
    assert loaded_preferences.quote_color_mode is QuoteColorMode.COLOR
    assert loaded_preferences.quote_image_mode is QuoteImageMode.BACKGROUND
    assert loaded_preferences.accessibility_plain_text is True
    assert loaded_preferences.accessibility_high_contrast is True
    assert loaded_preferences.accessibility_reduce_motion is True
    assert loaded_preferences.accessibility_verbose is True
    assert await sessions.get(owner, session.session_id) == session
    assert await sessions.get(99, session.session_id) is None


@pytest.mark.asyncio
async def test_reminder_claim_is_single_owner_operation(database: Database) -> None:
    now = datetime.now(UTC)
    reminder = Reminder(
        reminder_id=uuid4(),
        owner_id=42,
        due_at_utc=now - timedelta(seconds=1),
        payload="maintenance",
        status=ReminderStatus.PENDING,
    )
    repository = SQLReminderRepository(database)
    await repository.create(reminder)

    assert await repository.claim(reminder.reminder_id, now) is True
    assert await repository.claim(reminder.reminder_id, now) is False
    await repository.mark_delivered(reminder.reminder_id)
    assert (await repository.due(now)) == ()


@pytest.mark.asyncio
async def test_database_migrate_skips_an_already_current_sqlite_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'migrate.db'}")
    try:
        await database.migrate()

        def fail_if_called(url: str, directory: Path) -> None:
            del url, directory
            raise AssertionError("an already-current database should not run Alembic again")

        monkeypatch.setattr(Database, "_run_migrations", staticmethod(fail_if_called))
        await database.migrate()
    finally:
        await database.close()
