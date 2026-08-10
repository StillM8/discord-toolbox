"""Add SQLite FTS5 indexing for owner-scoped saved-item search."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_saved_items_fts"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS saved_items_fts
        USING fts5(id UNINDEXED, owner_id UNINDEXED, title, text, source_url)
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS saved_items_fts_ai
        AFTER INSERT ON saved_items
        BEGIN
            INSERT INTO saved_items_fts(id, owner_id, title, text, source_url)
            VALUES (new.id, new.owner_id, COALESCE(new.title, ''),
                    COALESCE(new.text, ''), COALESCE(new.source_url, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS saved_items_fts_au
        AFTER UPDATE ON saved_items
        BEGIN
            DELETE FROM saved_items_fts WHERE id = old.id;
            INSERT INTO saved_items_fts(id, owner_id, title, text, source_url)
            VALUES (new.id, new.owner_id, COALESCE(new.title, ''),
                    COALESCE(new.text, ''), COALESCE(new.source_url, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS saved_items_fts_ad
        AFTER DELETE ON saved_items
        BEGIN
            DELETE FROM saved_items_fts WHERE id = old.id;
        END
        """
    )

    # Populate the index when upgrading an existing 0001 database.
    op.execute(
        """
        INSERT INTO saved_items_fts(id, owner_id, title, text, source_url)
        SELECT id, owner_id, COALESCE(title, ''), COALESCE(text, ''), COALESCE(source_url, '')
        FROM saved_items
        WHERE id NOT IN (SELECT id FROM saved_items_fts)
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_au")
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_ai")
    op.execute("DROP TABLE IF EXISTS saved_items_fts")
