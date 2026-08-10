"""Portable export of the owner's saved-item vault."""

from __future__ import annotations

from datetime import UTC

from toolbox.core.contracts import AssetStore, SavedItemRepository
from toolbox.core.models import FileResult, ToolRequest, ToolResult


class VaultExportCapability:
    """Export saved bookmarks as a private, portable Markdown file."""

    def __init__(self, repository: SavedItemRepository, assets: AssetStore) -> None:
        self._repository = repository
        self._assets = assets

    async def execute(self, request: ToolRequest) -> ToolResult:
        items = await self._repository.search(request.actor.user.user_id, "")
        lines = [
            "# Toolbox bookmarks",
            "",
            "This export contains only the bookmarks owned by the requesting user.",
            "",
        ]
        for item in items:
            lines.append(f"## {item.title or item.kind.value}")
            lines.append("")
            if item.text:
                lines.append(item.text)
                lines.append("")
            if item.tags:
                lines.append(f"Tags: {', '.join(item.tags)}")
            if item.source_url:
                lines.append(f"Source: {item.source_url}")
            lines.append(f"Saved: {item.created_at.astimezone(UTC).isoformat()}")
            lines.append(f"ID: {item.item_id}")
            lines.append("")

        data = "\n".join(lines).encode("utf-8")
        asset = await self._assets.put(
            data,
            owner_id=request.actor.user.user_id,
            mime_type="text/markdown",
            ttl_seconds=3_600,
        )
        return FileResult(
            asset=asset,
            filename="toolbox-bookmarks.md",
            title=f"Exported {len(items)} bookmark(s)",
        )
