"""SQL context-basket repository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolbox.core.contracts import Clock, ContextStore
from toolbox.core.models import AssetRef, AttachmentRef, ContextItem, MessageContext
from toolbox.storage.database import Database
from toolbox.storage.models import ContextItemRow


class SQLContextStore(ContextStore):
    """Persist explicitly selected context with owner and TTL boundaries."""

    def __init__(
        self,
        database: Database,
        clock: Clock,
        *,
        max_items: int = 12,
        ttl_seconds: int = 1_800,
    ) -> None:
        self._database = database
        self._clock = clock
        self._max_items = max_items
        self._ttl_seconds = ttl_seconds

    async def add(self, item: ContextItem) -> None:
        expires_at = (
            item.asset.expires_at
            if item.asset and item.asset.expires_at
            else self._clock.now() + timedelta(seconds=self._ttl_seconds)
        )
        message_data = self._message_to_data(item.message) if item.message else None
        async with self._database.sessions() as session:
            await session.execute(
                delete(ContextItemRow).where(
                    ContextItemRow.owner_id == item.owner_id,
                    ContextItemRow.id == str(item.item_id),
                )
            )
            session.add(
                ContextItemRow(
                    id=str(item.item_id),
                    owner_id=item.owner_id,
                    label=item.label,
                    text=item.text,
                    message_data=message_data,
                    asset_id=str(item.asset.asset_id) if item.asset else None,
                    asset_mime_type=item.asset.mime_type if item.asset else None,
                    asset_size=item.asset.size if item.asset else None,
                    asset_expires_at=item.asset.expires_at if item.asset else None,
                    expires_at=expires_at,
                )
            )
            await session.commit()
            await self._trim(session, item.owner_id)

    async def list(self, owner_id: int) -> Sequence[ContextItem]:
        now = self._clock.now()
        async with self._database.sessions() as session:
            await session.execute(
                delete(ContextItemRow).where(
                    ContextItemRow.owner_id == owner_id,
                    ContextItemRow.expires_at <= now,
                )
            )
            await session.commit()
            result = await session.execute(
                select(ContextItemRow)
                .where(ContextItemRow.owner_id == owner_id, ContextItemRow.expires_at > now)
                .order_by(ContextItemRow.created_at.asc())
            )
            return tuple(self._to_item(row) for row in result.scalars())

    async def clear(self, owner_id: int) -> None:
        async with self._database.sessions() as session:
            await session.execute(delete(ContextItemRow).where(ContextItemRow.owner_id == owner_id))
            await session.commit()

    async def _trim(self, session: AsyncSession, owner_id: int) -> None:
        result = await session.execute(
            select(ContextItemRow)
            .where(ContextItemRow.owner_id == owner_id)
            .order_by(ContextItemRow.created_at.desc())
        )
        rows = list(result.scalars())
        for row in rows[self._max_items :]:
            await session.delete(row)
        await session.commit()

    @staticmethod
    def _message_to_data(message: MessageContext | None) -> dict[str, object] | None:
        if message is None:
            return None
        return {
            "message_id": message.message_id,
            "author_id": message.author_id,
            "author_name": message.author_name,
            "content": message.content,
            "channel_id": message.channel_id,
            "guild_id": message.guild_id,
            "reply_to_message_id": message.reply_to_message_id,
            "attachments": [
                {
                    "attachment_id": attachment.attachment_id,
                    "source_url": attachment.source_url,
                    "filename": attachment.filename,
                    "declared_content_type": attachment.declared_content_type,
                    "declared_size": attachment.declared_size,
                }
                for attachment in message.attachments
            ],
        }

    @staticmethod
    def _to_item(row: ContextItemRow) -> ContextItem:
        message = SQLContextStore._message_from_data(row.message_data)
        asset = (
            AssetRef(
                asset_id=UUID(row.asset_id),
                mime_type=row.asset_mime_type or "application/octet-stream",
                size=row.asset_size or 0,
                owner_id=row.owner_id,
                expires_at=row.asset_expires_at,
            )
            if row.asset_id
            else None
        )
        return ContextItem(
            item_id=UUID(row.id),
            owner_id=row.owner_id,
            label=row.label,
            text=row.text,
            message=message,
            asset=asset,
        )

    @staticmethod
    def _message_from_data(data: dict[str, object] | None) -> MessageContext | None:
        if data is None:
            return None
        attachments_data = data.get("attachments")
        attachments: list[AttachmentRef] = []
        if isinstance(attachments_data, list):
            for raw in cast(list[object], attachments_data):
                if not isinstance(raw, dict):
                    continue
                item = cast(Mapping[str, object], raw)
                attachments.append(
                    AttachmentRef(
                        attachment_id=str(item.get("attachment_id", "")),
                        source_url=str(item.get("source_url", "")),
                        filename=str(item.get("filename", "")),
                        declared_content_type=(
                            str(item["declared_content_type"])
                            if item.get("declared_content_type") is not None
                            else None
                        ),
                        declared_size=SQLContextStore._as_int(item.get("declared_size")),
                    )
                )
        return MessageContext(
            message_id=SQLContextStore._as_int(data.get("message_id")),
            author_id=SQLContextStore._as_int(data.get("author_id")),
            author_name=str(data.get("author_name", "unknown")),
            content=str(data.get("content", "")),
            channel_id=SQLContextStore._optional_int(data.get("channel_id")),
            guild_id=SQLContextStore._optional_int(data.get("guild_id")),
            reply_to_message_id=SQLContextStore._optional_int(data.get("reply_to_message_id")),
            attachments=tuple(attachments),
        )

    @staticmethod
    def _as_int(value: object, default: int = 0) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return SQLContextStore._as_int(value) if value is not None else None
