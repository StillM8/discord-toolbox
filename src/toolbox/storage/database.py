"""Async SQLAlchemy lifecycle owned by bootstrap."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base


class Database:
    """Create and close one async engine/session factory."""

    def __init__(self, url: str) -> None:
        self.url = url
        parsed = make_url(url)
        database_path = parsed.database
        if parsed.drivername.startswith("sqlite") and database_path not in {None, ":memory:"}:
            from pathlib import Path

            assert database_path is not None
            Path(database_path).expanduser().resolve().parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        self.engine: AsyncEngine = create_async_engine(url, future=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def migrate(self, script_directory: Path | None = None) -> None:
        """Apply committed Alembic migrations without blocking the event loop."""

        directory = script_directory or self._default_migration_directory()
        if not directory.is_dir():
            raise RuntimeError(f"Alembic migration directory does not exist: {directory}")
        if self._sqlite_is_at_head(self.url, directory):
            return
        await asyncio.to_thread(self._run_migrations, self.url, directory)

    async def create_schema(self) -> None:
        """Create schema objects for isolated repository tests.

        Application startup uses :meth:`migrate`. This helper intentionally remains
        available for fast unit tests that construct a database directly.
        """

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.exec_driver_sql(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS saved_items_fts
                USING fts5(id UNINDEXED, owner_id UNINDEXED, title, text, source_url, tags)
                """
            )
            await self._create_saved_items_fts_triggers(connection)

    def session(self) -> AsyncSession:
        """Return a session; callers own its transaction boundary."""

        return self.sessions()

    async def close(self) -> None:
        await self.engine.dispose()

    @staticmethod
    def _default_migration_directory() -> Path:
        """Locate migrations in both a source checkout and the Docker image."""

        candidates = (
            Path(__file__).resolve().parents[3] / "migrations",
            Path.cwd() / "migrations",
        )
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[0]

    @staticmethod
    def _sqlite_is_at_head(url: str, directory: Path) -> bool:
        """Avoid a no-op Alembic writer pass on an already-current SQLite file."""

        parsed = make_url(url)
        database_path = parsed.database
        if not parsed.drivername.startswith("sqlite") or database_path in {None, ":memory:"}:
            return False
        config_path = directory.parent / "alembic.ini"
        config = Config(str(config_path) if config_path.is_file() else None)
        config.set_main_option("script_location", str(directory))
        heads = set(ScriptDirectory.from_config(config).get_heads())
        if not heads:
            return False
        try:
            assert database_path is not None
            with sqlite3.connect(database_path, timeout=1.0) as connection:
                rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        except sqlite3.Error:
            return False
        return {str(row[0]) for row in rows} == heads

    @staticmethod
    def _run_migrations(url: str, directory: Path) -> None:
        """Run Alembic's synchronous command API in a worker thread."""

        config_path = directory.parent / "alembic.ini"
        config = Config(str(config_path) if config_path.is_file() else None)
        config.set_main_option("script_location", str(directory))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "head")

    @staticmethod
    async def _create_saved_items_fts_triggers(connection: AsyncConnection) -> None:
        """Create SQLite-only maintenance triggers for the test schema helper."""

        await connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS saved_items_fts_ai
            AFTER INSERT ON saved_items
            BEGIN
                INSERT INTO saved_items_fts(id, owner_id, title, text, source_url, tags)
                VALUES (new.id, new.owner_id, COALESCE(new.title, ''),
                        COALESCE(new.text, ''), COALESCE(new.source_url, ''),
                        COALESCE(new.tags, ''));
            END
            """
        )
        await connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS saved_items_fts_au
            AFTER UPDATE ON saved_items
            BEGIN
                DELETE FROM saved_items_fts WHERE id = old.id;
                INSERT INTO saved_items_fts(id, owner_id, title, text, source_url, tags)
                VALUES (new.id, new.owner_id, COALESCE(new.title, ''),
                        COALESCE(new.text, ''), COALESCE(new.source_url, ''),
                        COALESCE(new.tags, ''));
            END
            """
        )
        await connection.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS saved_items_fts_ad
            AFTER DELETE ON saved_items
            BEGIN
                DELETE FROM saved_items_fts WHERE id = old.id;
            END
            """
        )
