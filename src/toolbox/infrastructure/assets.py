"""Local application-owned asset storage."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from toolbox.core.contracts import AssetStore, Clock
from toolbox.core.errors import AssetRejected, InvalidRequest
from toolbox.core.models import AssetRef


class LocalAssetStore(AssetStore):
    """Store validated bytes beneath one configured directory."""

    def __init__(
        self,
        root: Path,
        clock: Clock,
        *,
        max_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self._root = root.resolve()
        self._clock = clock
        self._max_bytes = max_bytes

    async def initialize(self) -> None:
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)

    async def put(
        self,
        data: bytes,
        *,
        owner_id: int,
        mime_type: str,
        ttl_seconds: int | None = None,
    ) -> AssetRef:
        if owner_id <= 0 or not mime_type or len(data) > self._max_bytes:
            raise AssetRejected

        asset_id = uuid4()
        path = self._path(asset_id)
        await asyncio.to_thread(path.write_bytes, data)
        expires_at = (
            self._clock.now() + timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
        )
        await asyncio.to_thread(
            self._metadata_path(asset_id).write_text,
            json.dumps(
                {
                    "owner_id": owner_id,
                    "mime_type": mime_type,
                    "size": len(data),
                    "expires_at": expires_at.isoformat() if expires_at else None,
                }
            ),
            encoding="utf-8",
        )
        return AssetRef(
            asset_id=asset_id,
            mime_type=mime_type,
            size=len(data),
            owner_id=owner_id,
            expires_at=expires_at,
        )

    async def read(self, asset: AssetRef) -> bytes:
        self._validate_asset(asset)
        if asset.expires_at is not None and asset.expires_at <= self._clock.now():
            raise InvalidRequest
        try:
            return await asyncio.to_thread(self._path(asset.asset_id).read_bytes)
        except FileNotFoundError as error:
            raise InvalidRequest from error

    async def delete(self, asset: AssetRef) -> None:
        self._validate_asset(asset)
        try:
            await asyncio.to_thread(self._path(asset.asset_id).unlink)
        except FileNotFoundError:
            pass
        try:
            await asyncio.to_thread(self._metadata_path(asset.asset_id).unlink)
        except FileNotFoundError:
            return

    async def cleanup_expired(self) -> int:
        """Remove expired bytes and metadata after a restart-safe scan."""

        now = self._clock.now()
        removed = 0
        for metadata_path in await asyncio.to_thread(lambda: tuple(self._root.glob("*.json"))):
            try:
                raw = await asyncio.to_thread(metadata_path.read_text, encoding="utf-8")
                metadata = json.loads(raw)
                expires_at = metadata.get("expires_at")
                if not expires_at:
                    continue
                from datetime import datetime

                expiry = datetime.fromisoformat(str(expires_at))
                if expiry > now:
                    continue
                asset_id = UUID(metadata_path.stem)
                try:
                    await asyncio.to_thread(self._path(asset_id).unlink)
                except FileNotFoundError:
                    pass
                await asyncio.to_thread(metadata_path.unlink)
                removed += 1
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return removed

    def _path(self, asset_id: UUID) -> Path:
        path = (self._root / f"{asset_id}.bin").resolve()
        if path.parent != self._root:
            raise InvalidRequest
        return path

    def _metadata_path(self, asset_id: UUID) -> Path:
        path = (self._root / f"{asset_id}.json").resolve()
        if path.parent != self._root:
            raise InvalidRequest
        return path

    def _validate_asset(self, asset: AssetRef) -> None:
        if asset.owner_id <= 0 or asset.size < 0 or asset.size > self._max_bytes:
            raise InvalidRequest
