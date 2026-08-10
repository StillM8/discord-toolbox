"""Add tags and asset metadata to the personal saved-item vault."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_personal_vault"
down_revision: str | None = "0003_quote_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saved_items",
        sa.Column("tags", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "saved_items",
        sa.Column("asset_mime_type", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "saved_items",
        sa.Column("asset_size", sa.Integer(), nullable=True),
    )

    # FTS5 virtual tables cannot be altered in-place. Rebuild the small local
    # index while preserving all durable saved rows.
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_au")
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_ai")
    op.execute("DROP TABLE IF EXISTS saved_items_fts")
    op.execute(
        """
        CREATE VIRTUAL TABLE saved_items_fts
        USING fts5(id UNINDEXED, owner_id UNINDEXED, title, text, source_url, tags)
        """
    )
    op.execute(
        """
        INSERT INTO saved_items_fts(id, owner_id, title, text, source_url, tags)
        SELECT id, owner_id, COALESCE(title, ''), COALESCE(text, ''),
               COALESCE(source_url, ''), COALESCE(tags, '')
        FROM saved_items
        """
    )
    op.execute(
        """
        CREATE TRIGGER saved_items_fts_ai
        AFTER INSERT ON saved_items
        BEGIN
            INSERT INTO saved_items_fts(id, owner_id, title, text, source_url, tags)
            VALUES (new.id, new.owner_id, COALESCE(new.title, ''),
                    COALESCE(new.text, ''), COALESCE(new.source_url, ''),
                    COALESCE(new.tags, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER saved_items_fts_au
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
    op.execute(
        """
        CREATE TRIGGER saved_items_fts_ad
        AFTER DELETE ON saved_items
        BEGIN
            DELETE FROM saved_items_fts WHERE id = old.id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_au")
    op.execute("DROP TRIGGER IF EXISTS saved_items_fts_ai")
    op.execute("DROP TABLE IF EXISTS saved_items_fts")
    op.drop_column("saved_items", "asset_size")
    op.drop_column("saved_items", "asset_mime_type")
    op.drop_column("saved_items", "tags")
