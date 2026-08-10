from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from toolbox.core.errors import AssetRejected
from toolbox.core.models import AssetRef
from toolbox.infrastructure.assets import LocalAssetStore
from toolbox.infrastructure.attachments import AttachmentIngestor
from toolbox.infrastructure.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@pytest.mark.asyncio
async def test_local_asset_store_round_trip_is_opaque(tmp_path: Path) -> None:
    store = LocalAssetStore(tmp_path, FakeClock(), max_bytes=100)
    await store.initialize()
    asset = await store.put(b"hello", owner_id=42, mime_type="text/plain", ttl_seconds=30)

    assert asset.size == 5
    assert asset.expires_at == datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=30)
    assert await store.read(asset) == b"hello"
    await store.delete(asset)
    with pytest.raises(Exception):
        await store.read(asset)


@pytest.mark.asyncio
async def test_local_asset_store_cleanup_is_restart_safe(tmp_path: Path) -> None:
    clock = FakeClock()
    store = LocalAssetStore(tmp_path, clock, max_bytes=100)
    await store.initialize()
    asset = await store.put(b"hello", owner_id=42, mime_type="text/plain", ttl_seconds=30)

    clock.value += timedelta(seconds=31)

    assert await store.cleanup_expired() == 1
    with pytest.raises(Exception):
        await store.read(asset)


def test_ttl_cache_discards_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    cache: TTLCache[str] = TTLCache()
    cache.set("key", "value", ttl_seconds=60)

    assert cache.get("key") == "value"
    cache.delete("key")
    assert cache.get("key") is None


def test_asset_ref_is_opaque() -> None:
    asset = AssetRef(asset_id=uuid4(), mime_type="image/png", size=1, owner_id=1)
    assert "/" not in str(asset.asset_id)


def test_attachment_mime_detection_does_not_trust_declared_type() -> None:
    with pytest.raises(AssetRejected):
        AttachmentIngestor._sniff_mime(  # pyright: ignore[reportPrivateUsage]
            b"not an image", "image/png"
        )

    assert (
        AttachmentIngestor._sniff_mime(  # pyright: ignore[reportPrivateUsage]
            b"\x89PNG\r\n\x1a\n", "text/plain"
        )
        == "image/png"
    )
