"""Small, bounded application actions attached to generic results."""

from __future__ import annotations

from uuid import UUID

from toolbox.core.models import ActionKind, ToolAction


def share_action() -> ToolAction:
    """Offer a private-result-to-public share transition."""

    return ToolAction(kind=ActionKind.SHARE, label="Share")


def send_dm_action(item_id: UUID) -> ToolAction:
    """Offer an owner-authorized copy of a saved item in the owner's DM."""

    return ToolAction(
        kind=ActionKind.SEND_DM,
        label="Send to DM",
        target_id=item_id,
    )
