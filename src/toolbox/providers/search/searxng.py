"""SearXNG search adapter for the private Toolbox deployment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import httpx
from aiolimiter import AsyncLimiter

from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import SearchHit, SearchKind, SearchPage, SearchRequest


class SearXNGSearchProvider:
    """Consume SearXNG's JSON search endpoint and return provider data only."""

    _categories = {
        SearchKind.WEB: "general",
        SearchKind.IMAGES: "images",
        SearchKind.NEWS: "news",
        SearchKind.VIDEO: "videos",
    }

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "http://searxng:8080",
        limiter: AsyncLimiter | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._limiter = limiter or AsyncLimiter(max_rate=8, time_period=1)

    async def search(self, request: SearchRequest) -> SearchPage:
        query = request.query.strip()
        if not query or len(query) > 500:
            raise InvalidRequest
        page = self._parse_page(request.cursor)
        limit = min(max(request.limit, 1), 20)
        try:
            async with self._limiter:
                response = await self._client.get(
                    f"{self._base_url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "categories": self._categories[request.kind],
                        "pageno": page,
                        "safesearch": self._safe_search(request.safe_search),
                    },
                )
        except httpx.TimeoutException as error:
            raise ProviderTimeout from error
        except httpx.HTTPError as error:
            raise ProviderUnavailable from error

        if response.status_code == 429:
            raise RateLimited
        if response.status_code >= 500:
            raise ProviderUnavailable
        if response.status_code >= 400:
            raise InvalidRequest
        try:
            body = response.json()
        except ValueError as error:
            raise ProviderUnavailable from error

        hits = tuple(
            hit
            for hit in (self._parse_hit(item, request.kind) for item in self._results(body))
            if hit is not None
        )
        return SearchPage(
            query=query,
            kind=request.kind,
            hits=hits[:limit],
            next_cursor=str(page + 1) if len(hits) >= limit else None,
        )

    @staticmethod
    def _parse_page(cursor: str | None) -> int:
        if cursor is None:
            return 1
        try:
            page = int(cursor)
        except ValueError as error:
            raise InvalidRequest from error
        if page < 1 or page > 100:
            raise InvalidRequest
        return page

    @staticmethod
    def _safe_search(value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"0", "1", "2"}:
            return normalized
        return {"off": "0", "moderate": "1", "strict": "2"}.get(normalized, "1")

    @staticmethod
    def _results(body: object) -> list[object]:
        if not isinstance(body, dict):
            raise ProviderUnavailable
        values = cast(Mapping[str, object], body).get("results")
        return cast(list[object], values) if isinstance(values, list) else []

    @staticmethod
    def _parse_hit(item: object, kind: SearchKind) -> SearchHit | None:
        if not isinstance(item, dict):
            return None
        data = cast(Mapping[str, object], item)
        title = data.get("title")
        url = data.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            return None

        snippet = data.get("content") or data.get("description") or data.get("snippet")
        source = data.get("engine") or data.get("source")
        if isinstance(source, list):
            source_values = cast(list[object], source)
            source = ", ".join(str(value) for value in source_values[:3])
        thumbnail = data.get("thumbnail") or data.get("thumbnail_src") or data.get("img_src")
        return SearchHit(
            title=title,
            url=url,
            snippet=snippet if isinstance(snippet, str) else None,
            source_name=source if isinstance(source, str) else kind.value,
            thumbnail_url=thumbnail if isinstance(thumbnail, str) else None,
        )
