"""SQL saved-item repository."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from toolbox.core.contracts import SavedItemRepository
from toolbox.core.models import SavedItem, SavedItemKind
from toolbox.storage.database import Database
from toolbox.storage.models import SavedItemRow, as_utc


class SQLSavedItemRepository(SavedItemRepository):
    """Store and search owner-scoped saved items."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def save(self, item: SavedItem) -> None:
        async with self._database.sessions() as session:
            existing = await session.get(SavedItemRow, str(item.item_id))
            if existing is None:
                existing = SavedItemRow(id=str(item.item_id), owner_id=item.owner_id)
                session.add(existing)
            existing.kind = item.kind.value
            existing.title = item.title
            existing.text = item.text
            existing.source_url = item.source_url
            existing.asset_id = str(item.asset_id) if item.asset_id else None
            existing.tags = ",".join(item.tags)
            existing.asset_mime_type = item.asset_mime_type
            existing.asset_size = item.asset_size
            existing.created_at = item.created_at
            await session.commit()

    async def get(self, owner_id: int, item_id: UUID) -> SavedItem | None:
        async with self._database.sessions() as session:
            row = await session.scalar(
                select(SavedItemRow).where(
                    SavedItemRow.id == str(item_id),
                    SavedItemRow.owner_id == owner_id,
                )
            )
            return self._to_item(row) if row is not None else None

    async def search(self, owner_id: int, query: str) -> tuple[SavedItem, ...]:
        normalized_query = query.strip()
        async with self._database.sessions() as session:
            if normalized_query:
                fts_items = await self._fts_search(session, owner_id, normalized_query)
                if fts_items is not None:
                    return fts_items

            pattern = f"%{normalized_query}%"
            result = await session.execute(
                select(SavedItemRow)
                .where(
                    SavedItemRow.owner_id == owner_id,
                    or_(
                        SavedItemRow.title.ilike(pattern),
                        SavedItemRow.text.ilike(pattern),
                        SavedItemRow.source_url.ilike(pattern),
                        SavedItemRow.tags.ilike(pattern),
                    ),
                )
                .order_by(SavedItemRow.created_at.desc())
            )
            return tuple(self._to_item(row) for row in result.scalars())

    async def _fts_search(
        self,
        session: AsyncSession,
        owner_id: int,
        query: str,
    ) -> tuple[SavedItem, ...] | None:
        """Use FTS5 when the migrated SQLite schema provides it.

        The fallback keeps repository tests and older databases usable while the
        migration is being applied. User input is quoted as one FTS phrase so it
        cannot inject FTS operators.
        """

        escaped = query.replace('"', '""')
        match = f'"{escaped}"'
        try:
            result = await session.execute(
                text(
                    """
                    SELECT id
                    FROM saved_items_fts
                    WHERE owner_id = :owner_id AND saved_items_fts MATCH :match
                    ORDER BY rank
                    LIMIT 50
                    """
                ),
                {"owner_id": owner_id, "match": match},
            )
        except DBAPIError:
            return None

        item_ids = tuple(str(row[0]) for row in result.all())
        if not item_ids:
            return ()
        rows = await session.execute(
            select(SavedItemRow).where(
                SavedItemRow.owner_id == owner_id,
                SavedItemRow.id.in_(item_ids),
            )
        )
        by_id = {row.id: self._to_item(row) for row in rows.scalars()}
        return tuple(by_id[item_id] for item_id in item_ids if item_id in by_id)

    async def delete(self, owner_id: int, item_id: UUID) -> None:
        async with self._database.sessions() as session:
            await session.execute(
                delete(SavedItemRow).where(
                    SavedItemRow.id == str(item_id),
                    SavedItemRow.owner_id == owner_id,
                )
            )
            await session.commit()

    @staticmethod
    def _to_item(row: SavedItemRow) -> SavedItem:
        return SavedItem(
            item_id=UUID(row.id),
            owner_id=row.owner_id,
            kind=SavedItemKind(row.kind),
            title=row.title,
            text=row.text,
            source_url=row.source_url,
            asset_id=UUID(row.asset_id) if row.asset_id else None,
            created_at=as_utc(row.created_at),
            tags=tuple(tag for tag in (row.tags or "").split(",") if tag),
            asset_mime_type=row.asset_mime_type,
            asset_size=row.asset_size,
        )
