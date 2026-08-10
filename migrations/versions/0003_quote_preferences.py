"""Persist owner quote-card style preferences."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_quote_preferences"
down_revision: str | None = "0002_saved_items_fts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column("quote_font", sa.String(length=20), nullable=False, server_default="sans"),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "quote_text_position",
            sa.String(length=20),
            nullable=False,
            server_default="center",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "quote_color_mode",
            sa.String(length=20),
            nullable=False,
            server_default="grayscale",
        ),
    )
    op.add_column(
        "user_preferences",
        sa.Column("quote_image_mode", sa.String(length=20), nullable=False, server_default="left"),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "quote_image_mode")
    op.drop_column("user_preferences", "quote_color_mode")
    op.drop_column("user_preferences", "quote_text_position")
    op.drop_column("user_preferences", "quote_font")
