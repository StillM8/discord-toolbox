"""Optional GIPHY search adapter returning normalized provider data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import httpx
from aiolimiter import AsyncLimiter

from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import SearchHit, SearchKind, SearchPage, SearchRequest


class GiphySearchProvider:
    """Use GIPHY search only when an explicitly configured key enables it."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        base_url: str = "https://api.giphy.com/v1",
        limiter: AsyncLimiter | None = None,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._limiter = limiter or AsyncLimiter(max_rate=4, time_period=1)

    async def search(self, request: SearchRequest) -> SearchPage:
        query = request.query.strip()
        if not self._api_key or not query or len(query) > 50:
            raise InvalidRequest
        limit = min(max(request.limit, 1), 50)
        offset = self._parse_cursor(request.cursor)
        params: dict[str, str | int] = {
            "api_key": self._api_key,
            "q": query,
            "limit": limit,
            "offset": offset,
            "rating": "g",
            "lang": "en",
        }
        try:
            async with self._limiter:
                response = await self._client.get(
                    f"{self._base_url}/gifs/search",
                    params=params,
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

        raw_items = self._raw_items(body)
        hits = tuple(
            hit for hit in (self._parse_hit(item) for item in raw_items) if hit is not None
        )
        return SearchPage(
            query=query,
            kind=SearchKind.GIF,
            hits=hits[:limit],
            next_cursor=str(offset + limit) if len(hits) >= limit else None,
        )

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        try:
            offset = int(cursor)
        except ValueError as error:
            raise InvalidRequest from error
        if offset < 0 or offset > 1_000:
            raise InvalidRequest
        return offset

    @staticmethod
    def _raw_items(body: object) -> list[object]:
        if not isinstance(body, dict):
            raise ProviderUnavailable
        data = cast(Mapping[str, object], body).get("data")
        return cast(list[object], data) if isinstance(data, list) else []

    @staticmethod
    def _parse_hit(item: object) -> SearchHit | None:
        if not isinstance(item, dict):
            return None
        data = cast(Mapping[str, object], item)
        page_url = data.get("url")
        title = data.get("title") or "GIF"
        images = data.get("images")
        if (
            not isinstance(page_url, str)
            or not isinstance(title, str)
            or not isinstance(images, dict)
        ):
            return None
        image_map = cast(Mapping[str, object], images)
        original = GiphySearchProvider._image_url(image_map.get("original"))
        preview = GiphySearchProvider._image_url(image_map.get("fixed_width_small")) or original
        if original is None:
            return None
        return SearchHit(
            title=title or "GIF",
            url=page_url,
            snippet="GIPHY",
            source_name="GIPHY",
            thumbnail_url=preview,
        )

    @staticmethod
    def _image_url(value: object) -> str | None:
        if not isinstance(value, dict):
            return None
        url = cast(Mapping[str, object], value).get("url")
        return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None
