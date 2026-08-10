"""One managed async HTTP client shared by external providers."""

from __future__ import annotations

from typing import Any

import httpx


class ManagedHttpClient:
    """Own one pooled HTTP client for the application lifecycle."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            headers={"User-Agent": "Toolbox/0.1 (+https://discord.com)"},
        )

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        await self.close()
