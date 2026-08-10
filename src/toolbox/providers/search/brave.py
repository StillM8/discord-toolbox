"""Brave Search adapter returning normalized provider data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import httpx

from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import SearchHit, SearchKind, SearchPage, SearchRequest


class BraveSearchProvider:
    """Use Brave's web/image/news/video endpoints behind one contract."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: str,
        base_url: str = "https://api.search.brave.com/res/v1",
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def search(self, request: SearchRequest) -> SearchPage:
        if not self._api_key or not request.query.strip():
            raise InvalidRequest

        limit = min(max(request.limit, 1), 20)
        offset = self._parse_cursor(request.cursor)
        endpoint = f"{self._base_url}/{request.kind.value}/search"
        params: dict[str, str | int] = {
            "q": request.query,
            "count": limit,
            "offset": offset,
            "safesearch": request.safe_search,
        }
        try:
            response = await self._client.get(
                endpoint,
                params=params,
                headers={"X-Subscription-Token": self._api_key, "Accept": "application/json"},
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
            self._parse_hit(item, request.kind)
            for item in self._raw_results(body, request.kind)
        )
        hits = tuple(hit for hit in hits if hit is not None)
        next_cursor = str(offset + limit) if len(hits) >= limit else None
        return SearchPage(
            query=request.query,
            kind=request.kind,
            hits=hits,
            next_cursor=next_cursor,
        )

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None:
            return 0
        try:
            value = int(cursor)
        except ValueError as error:
            raise InvalidRequest from error
        if value < 0 or value > 10_000:
            raise InvalidRequest
        return value

    @staticmethod
    def _raw_results(body: object, kind: SearchKind) -> list[object]:
        if not isinstance(body, dict):
            raise ProviderUnavailable
        body_map = cast(Mapping[str, object], body)
        if kind is SearchKind.WEB:
            section = body_map.get("web")
            if not isinstance(section, dict):
                return []
            results = cast(Mapping[str, object], section).get("results")
            return cast(list[object], results) if isinstance(results, list) else []
        section_key = {
            SearchKind.IMAGES: "images",
            SearchKind.NEWS: "news",
            SearchKind.VIDEO: "videos",
        }.get(kind, "results")
        section = body_map.get(section_key)
        if isinstance(section, dict):
            values = cast(Mapping[str, object], section).get("results")
        else:
            values = section
        return cast(list[object], values) if isinstance(values, list) else []

    @staticmethod
    def _parse_hit(item: object, kind: SearchKind) -> SearchHit | None:
        if not isinstance(item, dict):
            return None
        data = cast(Mapping[str, object], item)
        title = data.get("title")
        url = data.get("url") or data.get("source_url")
        if not isinstance(title, str) or not isinstance(url, str):
            return None
        description = data.get("description") or data.get("snippet")
        source_name = data.get("source_name")
        profile = data.get("profile")
        if source_name is None and isinstance(profile, dict):
            profile_data = cast(Mapping[str, object], profile)
            source_name = profile_data.get("long_name") or profile_data.get("short_name")
        thumbnail_url = None
        thumbnail = data.get("thumbnail")
        if isinstance(thumbnail, dict):
            candidate = cast(Mapping[str, object], thumbnail).get("src")
            if isinstance(candidate, str):
                thumbnail_url = candidate
        return SearchHit(
            title=title,
            url=url,
            snippet=description if isinstance(description, str) else None,
            source_name=source_name if isinstance(source_name, str) else kind.value,
            thumbnail_url=thumbnail_url,
        )
