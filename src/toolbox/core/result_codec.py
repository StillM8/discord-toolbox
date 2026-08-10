"""Bounded serialization for short-lived private-result sessions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from .models import (
    AssetRef,
    ErrorResult,
    FactCheckResult,
    FileResult,
    ImageResult,
    SearchResultItem,
    SearchResults,
    SourceRef,
    TextResult,
    ToolResult,
    Visibility,
)


class ResultCodec:
    """Serialize only result data needed by a short-lived share action."""

    def encode(self, result: ToolResult) -> dict[str, str]:
        if isinstance(result, TextResult):
            return {
                "kind": "text",
                "title": result.title or "",
                "text": result.text,
                "input_text": self._bounded_input(result.input_text),
                "sources": json.dumps(
                    [
                        {
                            "title": source.title,
                            "url": source.url,
                            "source_name": source.source_name,
                        }
                        for source in result.sources
                    ],
                    separators=(",", ":"),
                ),
            }
        if isinstance(result, SearchResults):
            return {
                "kind": "search",
                "query": result.query,
                "search_kind": result.kind.value,
                "items": json.dumps(
                    [
                        {
                            "title": item.title,
                            "url": item.url,
                            "snippet": item.snippet,
                            "source_name": item.source_name,
                            "thumbnail_url": item.thumbnail_url,
                        }
                        for item in result.items
                    ],
                    separators=(",", ":"),
                ),
            }
        if isinstance(result, ImageResult):
            return {
                "kind": "image",
                "title": result.title or "",
                "input_text": self._bounded_input(result.input_text),
                **self._asset_fields(result.asset),
            }
        if isinstance(result, FileResult):
            return {
                "kind": "file",
                "filename": result.filename,
                "title": result.title or "",
                "input_text": self._bounded_input(result.input_text),
                **self._asset_fields(result.asset),
            }
        if isinstance(result, FactCheckResult):
            return {
                "kind": "fact_check",
                "claim": result.claim,
                "verdict": result.verdict.value,
                "explanation": result.explanation,
                "sources": json.dumps(
                    [
                        {
                            "title": source.title,
                            "url": source.url,
                            "source_name": source.source_name,
                        }
                        for source in result.sources
                    ],
                    separators=(",", ":"),
                ),
            }
        raise ValueError("That result cannot be shared.")

    def decode(self, payload: Mapping[str, str]) -> ToolResult:
        kind = payload.get("kind")
        if kind == "text":
            raw_sources = json.loads(payload.get("sources", "[]"))
            if not isinstance(raw_sources, list):
                raise ValueError("Invalid text session")
            sources: list[SourceRef] = []
            for raw_source in cast(list[object], raw_sources):
                if not isinstance(raw_source, dict):
                    continue
                item = cast(Mapping[str, object], raw_source)
                sources.append(
                    SourceRef(
                        title=str(item.get("title", "")),
                        url=str(item.get("url", "")),
                        source_name=(
                            str(item["source_name"])
                            if item.get("source_name") is not None
                            else None
                        ),
                    )
                )
            return TextResult(
                title=payload.get("title") or None,
                text=payload.get("text", ""),
                input_text=payload.get("input_text") or None,
                sources=tuple(sources),
            )
        if kind == "search":
            raw_items = json.loads(payload.get("items", "[]"))
            if not isinstance(raw_items, list):
                raise ValueError("Invalid search session")
            items: list[SearchResultItem] = []
            for raw_item in cast(list[object], raw_items):
                if not isinstance(raw_item, dict):
                    continue
                item = cast(Mapping[str, object], raw_item)
                items.append(
                    SearchResultItem(
                        title=str(item.get("title", "")),
                        url=str(item.get("url", "")),
                        snippet=(str(item["snippet"]) if item.get("snippet") is not None else None),
                        source_name=(
                            str(item["source_name"])
                            if item.get("source_name") is not None
                            else None
                        ),
                        thumbnail_url=(
                            str(item["thumbnail_url"])
                            if item.get("thumbnail_url") is not None
                            else None
                        ),
                    )
                )
            from .models import SearchKind

            return SearchResults(
                query=payload.get("query", ""),
                items=tuple(items),
                kind=SearchKind(payload.get("search_kind", SearchKind.WEB.value)),
            )
        if kind == "image":
            return ImageResult(
                asset=self._asset_from_payload(payload),
                title=payload.get("title") or None,
                input_text=payload.get("input_text") or None,
            )
        if kind == "file":
            return FileResult(
                asset=self._asset_from_payload(payload),
                filename=payload.get("filename", "file.bin"),
                title=payload.get("title") or None,
                input_text=payload.get("input_text") or None,
            )
        if kind == "fact_check":
            raw_sources = json.loads(payload.get("sources", "[]"))
            if not isinstance(raw_sources, list):
                raise ValueError("Invalid fact-check session")
            sources: list[SourceRef] = []
            for raw_source in cast(list[object], raw_sources):
                if not isinstance(raw_source, dict):
                    continue
                item = cast(Mapping[str, object], raw_source)
                sources.append(
                    SourceRef(
                        title=str(item.get("title", "")),
                        url=str(item.get("url", "")),
                        source_name=(
                            str(item["source_name"])
                            if item.get("source_name") is not None
                            else None
                        ),
                    )
                )
            from .models import Verdict

            return FactCheckResult(
                claim=payload.get("claim", ""),
                verdict=Verdict(payload.get("verdict", "unverified")),
                explanation=payload.get("explanation", ""),
                sources=tuple(sources),
            )
        raise ValueError("That session is invalid or expired.")

    @staticmethod
    def public(result: ToolResult) -> ToolResult:
        if isinstance(
            result,
            (TextResult, SearchResults, ImageResult, FileResult, FactCheckResult),
        ):
            from dataclasses import replace

            return replace(result, visibility=Visibility.PUBLIC)
        if isinstance(result, ErrorResult):
            return result
        raise ValueError("That result cannot be shared.")

    @staticmethod
    def _asset_fields(asset: AssetRef) -> dict[str, str]:
        return {
            "asset_id": str(asset.asset_id),
            "mime_type": asset.mime_type,
            "size": str(asset.size),
            "owner_id": str(asset.owner_id),
            "expires_at": asset.expires_at.isoformat() if asset.expires_at else "",
        }

    @staticmethod
    def _bounded_input(value: str | None) -> str:
        """Keep user-supplied context bounded inside short-lived sessions."""

        if not value:
            return ""
        return value if len(value) <= 2_000 else f"{value[:1_999]}…"

    @staticmethod
    def _asset_from_payload(payload: Mapping[str, str]) -> AssetRef:
        from datetime import datetime

        expires = payload.get("expires_at")
        return AssetRef(
            asset_id=UUID(payload["asset_id"]),
            mime_type=payload.get("mime_type", "application/octet-stream"),
            size=int(payload.get("size", "0")),
            owner_id=int(payload.get("owner_id", "0")),
            expires_at=datetime.fromisoformat(expires) if expires else None,
        )
