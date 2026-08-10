"""Create the initial owner-scoped Toolbox tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_items_owner_id", "saved_items", ["owner_id"])

    op.create_table(
        "context_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("message_data", sa.JSON(), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("asset_mime_type", sa.String(length=200), nullable=True),
        sa.Column("asset_size", sa.Integer(), nullable=True),
        sa.Column("asset_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_context_items_owner_id", "context_items", ["owner_id"])
    op.create_index("ix_context_items_expires_at", "context_items", ["expires_at"])

    op.create_table(
        "user_preferences",
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("language", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("default_profile", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("owner_id"),
    )

    op.create_table(
        "reminders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("due_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminders_owner_id", "reminders", ["owner_id"])
    op.create_index("ix_reminders_due_at_utc", "reminders", ["due_at_utc"])
    op.create_index("ix_reminders_status", "reminders", ["status"])

    op.create_table(
        "interaction_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interaction_sessions_owner_id", "interaction_sessions", ["owner_id"])
    op.create_index("ix_interaction_sessions_expires_at", "interaction_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_interaction_sessions_expires_at", table_name="interaction_sessions")
    op.drop_index("ix_interaction_sessions_owner_id", table_name="interaction_sessions")
    op.drop_table("interaction_sessions")
    op.drop_index("ix_reminders_status", table_name="reminders")
    op.drop_index("ix_reminders_due_at_utc", table_name="reminders")
    op.drop_index("ix_reminders_owner_id", table_name="reminders")
    op.drop_table("reminders")
    op.drop_table("user_preferences")
    op.drop_index("ix_context_items_expires_at", table_name="context_items")
    op.drop_index("ix_context_items_owner_id", table_name="context_items")
    op.drop_table("context_items")
    op.drop_index("ix_saved_items_owner_id", table_name="saved_items")
    op.drop_table("saved_items")
