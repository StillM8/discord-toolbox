"""SQL interaction-session repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select

from toolbox.core.contracts import Clock, SessionStore
from toolbox.core.models import ActionKind, InteractionSession
from toolbox.storage.database import Database
from toolbox.storage.models import InteractionSessionRow, as_utc


class SQLSessionStore(SessionStore):
    """Store opaque component state and enforce owner/expiry on reads."""

    def __init__(self, database: Database, clock: Clock) -> None:
        self._database = database
        self._clock = clock

    async def create(self, session: InteractionSession) -> None:
        async with self._database.sessions() as db_session:
            db_session.add(
                InteractionSessionRow(
                    id=str(session.session_id),
                    owner_id=session.owner_id,
                    action=session.action.value,
                    target_id=str(session.target_id) if session.target_id else None,
                    payload=dict(session.payload),
                    expires_at=session.expires_at,
                )
            )
            await db_session.commit()

    async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
        now = self._clock.now()
        async with self._database.sessions() as db_session:
            row = await db_session.scalar(
                select(InteractionSessionRow).where(
                    InteractionSessionRow.id == str(session_id),
                    InteractionSessionRow.owner_id == owner_id,
                    InteractionSessionRow.expires_at > now,
                )
            )
            if row is None:
                return None
            return InteractionSession(
                session_id=UUID(row.id),
                owner_id=row.owner_id,
                action=ActionKind(row.action),
                target_id=UUID(row.target_id) if row.target_id else None,
                payload=dict(row.payload),
                expires_at=as_utc(row.expires_at),
            )

    async def delete(self, owner_id: int, session_id: UUID) -> None:
        async with self._database.sessions() as db_session:
            await db_session.execute(
                delete(InteractionSessionRow).where(
                    InteractionSessionRow.id == str(session_id),
                    InteractionSessionRow.owner_id == owner_id,
                )
            )
            await db_session.commit()
