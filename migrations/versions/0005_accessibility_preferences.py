"""Persist owner accessibility and presentation preferences."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_accessibility_preferences"
down_revision: str | None = "0004_personal_vault"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in (
        "accessibility_plain_text",
        "accessibility_high_contrast",
        "accessibility_reduce_motion",
        "accessibility_verbose",
    ):
        op.add_column(
            "user_preferences",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    for name in (
        "accessibility_verbose",
        "accessibility_reduce_motion",
        "accessibility_high_contrast",
        "accessibility_plain_text",
    ):
        op.drop_column("user_preferences", name)
