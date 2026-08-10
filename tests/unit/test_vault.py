from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from toolbox.capabilities.vault import VaultExportCapability
from toolbox.core.models import (
    ActorContext,
    AssetRef,
    CapabilityName,
    FileResult,
    InteractionContext,
    SavedItem,
    SavedItemKind,
    ToolRequest,
    UserContext,
)


@pytest.mark.asyncio
async def test_vault_export_contains_only_owner_bookmarks() -> None:
    owner_item = SavedItem(
        item_id=uuid4(),
        owner_id=42,
        kind=SavedItemKind.TEXT,
        title="Read later",
        text="private note",
        source_url="https://example.com/article",
        asset_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        tags=("read", "idea"),
    )

    class Repository:
        async def save(self, item: SavedItem) -> None:
            del item

        async def search(self, owner_id: int, query: str) -> Sequence[SavedItem]:
            assert owner_id == 42
            assert query == ""
            return (owner_item,)

        async def get(self, owner_id: int, item_id: UUID) -> SavedItem | None:
            return owner_item if owner_id == 42 and item_id == owner_item.item_id else None

        async def delete(self, owner_id: int, item_id: UUID) -> None:
            del owner_id, item_id

    class Assets:
        def __init__(self) -> None:
            self.data: bytes | None = None

        async def put(
            self,
            data: bytes,
            *,
            owner_id: int,
            mime_type: str,
            ttl_seconds: int | None = None,
        ) -> AssetRef:
            assert owner_id == 42
            assert mime_type == "text/markdown"
            assert ttl_seconds == 3_600
            self.data = data
            return AssetRef(uuid4(), mime_type, len(data), owner_id)

        async def read(self, asset: AssetRef) -> bytes:
            del asset
            return self.data or b""

        async def delete(self, asset: AssetRef) -> None:
            del asset

    request = ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.SAVED_EXPORT,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Owner")),
        interaction=InteractionContext(None, None, "dm"),
    )
    assets = Assets()
    result = await VaultExportCapability(Repository(), assets).execute(request)

    assert isinstance(result, FileResult)
    assert result.filename == "toolbox-bookmarks.md"
    assert assets.data is not None
    exported = assets.data.decode("utf-8")
    assert "private note" in exported
    assert "#read" not in exported
    assert "read, idea" in exported
