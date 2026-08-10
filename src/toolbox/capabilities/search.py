"""Application search capability; provider data never becomes Discord UI."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from toolbox.core.actions import share_action
from toolbox.core.contracts import Clock, SessionStore, WebSearchProvider
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    ActionKind,
    CapabilityName,
    ErrorResult,
    InteractionSession,
    SearchHit,
    SearchKind,
    SearchPage,
    SearchRequest,
    SearchResultItem,
    SearchResults,
    ToolAction,
    ToolRequest,
    ToolResult,
)


@dataclass(frozen=True, slots=True)
class _SearchState:
    """One displayed result and the provider state that follows it."""

    hit: SearchHit
    remaining_hits: tuple[SearchHit, ...]
    cursor: str | None


class SearchCapability:
    """Turn normalized provider pages into one-result application responses."""

    _max_history = 20

    def __init__(
        self,
        provider: WebSearchProvider,
        *,
        max_results: int = 5,
        sessions: SessionStore | None = None,
        clock: Clock | None = None,
        session_ttl_seconds: int = 1_800,
    ) -> None:
        self._provider = provider
        self._max_results = max(1, min(max_results, 20))
        self._sessions = sessions
        self._clock = clock
        self._session_ttl_seconds = session_ttl_seconds

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Return one result and create opaque sessions for navigation/actions."""

        session: InteractionSession | None = None
        history: tuple[_SearchState, ...] = ()
        current_hit: SearchHit | None = None
        remaining_hits: tuple[SearchHit, ...] = ()
        provider_cursor: str | None = None

        if request.session_id is not None:
            if self._sessions is None or self._clock is None:
                return self._error(InvalidRequest)
            session = await self._sessions.get(
                request.actor.user.user_id,
                request.session_id,
            )
            if session is None or session.action not in {
                ActionKind.NEXT_PAGE,
                ActionKind.PREVIOUS_PAGE,
            }:
                return self._error(InvalidRequest)
            query = session.payload.get("query", "").strip()
            if not query or len(query) > 500:
                return self._error(InvalidRequest)
            try:
                kind = self._kind(request, session_kind=session.payload.get("kind"))
                history = self._decode_history(session.payload.get("history"))
                if session.action is ActionKind.PREVIOUS_PAGE:
                    if not history:
                        return self._error(InvalidRequest)
                    previous = history[-1]
                    history = history[:-1]
                    current_hit = previous.hit
                    remaining_hits = previous.remaining_hits
                    provider_cursor = previous.cursor
                else:
                    current_hit = self._decode_hit(session.payload.get("current_hit"))
                    if current_hit is None:
                        return self._error(InvalidRequest)
                    source_remaining = self._decode_hits(session.payload.get("remaining_hits"))
                    source_cursor = session.payload.get("cursor") or None
                    if source_remaining:
                        page = SearchPage(
                            query=query,
                            kind=kind,
                            hits=source_remaining,
                            next_cursor=source_cursor,
                        )
                    else:
                        page = await self._provider.search(
                            SearchRequest(
                                query=query,
                                kind=kind,
                                cursor=source_cursor,
                                limit=self._max_results,
                            )
                        )
                    history = (
                        *history,
                        _SearchState(current_hit, source_remaining, source_cursor),
                    )[-self._max_history :]
                    current_hit = page.hits[0] if page.hits else None
                    remaining_hits = page.hits[1:] if current_hit is not None else ()
                    provider_cursor = page.next_cursor
            except ToolboxError as error:
                return self._error(error)
        else:
            query = (
                request.text
                or request.options.get("query")
                or (request.target_message.content if request.target_message else "")
            ).strip()
            if not query or len(query) > 500:
                return self._error(InvalidRequest)
            try:
                kind = self._kind(request)
                page = await self._provider.search(
                    SearchRequest(
                        query=query,
                        kind=kind,
                        cursor=request.options.get("cursor"),
                        limit=self._max_results,
                    )
                )
            except ToolboxError as error:
                return self._error(error)
            current_hit = page.hits[0] if page.hits else None
            remaining_hits = page.hits[1:] if current_hit is not None else ()
            provider_cursor = page.next_cursor
            query = page.query
            kind = page.kind

        result = await self._build_result(
            request,
            query=query,
            kind=kind,
            current_hit=current_hit,
            remaining_hits=remaining_hits,
            provider_cursor=provider_cursor,
            history=history,
        )
        if session is not None and self._sessions is not None:
            await self._sessions.delete(request.actor.user.user_id, session.session_id)
        return result

    async def _build_result(
        self,
        request: ToolRequest,
        *,
        query: str,
        kind: SearchKind,
        current_hit: SearchHit | None,
        remaining_hits: tuple[SearchHit, ...],
        provider_cursor: str | None,
        history: tuple[_SearchState, ...],
    ) -> SearchResults:
        if current_hit is None:
            return SearchResults(query=query, items=(), kind=kind)

        actions: list[ToolAction] = [share_action()]
        if (
            kind not in {SearchKind.IMAGES, SearchKind.GIF}
            and self._sessions is not None
            and self._clock is not None
            and current_hit.url
        ):
            expand_session_id = await self._create_session(
                request,
                ActionKind.EXPAND,
                {
                    "query": query,
                    "kind": kind.value,
                    "title": current_hit.title[:300],
                    "url": current_hit.url[:2_048],
                    "source_name": (current_hit.source_name or "")[:200],
                },
            )
            actions.append(
                ToolAction(
                    kind=ActionKind.EXPAND,
                    label="Expand",
                    session_id=expand_session_id,
                )
            )

        current_state = _SearchState(current_hit, remaining_hits, provider_cursor)
        if history and self._sessions is not None and self._clock is not None:
            previous_session_id = await self._create_session(
                request,
                ActionKind.PREVIOUS_PAGE,
                {
                    "query": query,
                    "kind": kind.value,
                    "history": self._encode_history(history),
                },
            )
            actions.append(
                ToolAction(
                    kind=ActionKind.PREVIOUS_PAGE,
                    label="Back",
                    session_id=previous_session_id,
                )
            )

        has_next = bool(remaining_hits) or provider_cursor is not None
        if has_next and self._sessions is not None and self._clock is not None:
            next_session_id = await self._create_session(
                request,
                ActionKind.NEXT_PAGE,
                {
                    "query": query,
                    "kind": kind.value,
                    "current_hit": json.dumps(self._hit_payload(current_state.hit)),
                    "remaining_hits": self._encode_hits(current_state.remaining_hits),
                    "history": self._encode_history(history),
                    **({"cursor": provider_cursor} if provider_cursor is not None else {}),
                },
            )
            actions.append(
                ToolAction(
                    kind=ActionKind.NEXT_PAGE,
                    label="Next result",
                    session_id=next_session_id,
                )
            )

        return SearchResults(
            query=query,
            items=(self._result_item(current_hit),),
            next_cursor=provider_cursor if has_next else None,
            kind=kind,
            actions=tuple(actions),
        )

    async def _create_session(
        self,
        request: ToolRequest,
        action: ActionKind,
        payload: Mapping[str, str],
    ) -> UUID:
        if self._sessions is None or self._clock is None:
            raise RuntimeError("Search sessions are not configured")
        session_id = uuid4()
        await self._sessions.create(
            InteractionSession(
                session_id=session_id,
                owner_id=request.actor.user.user_id,
                action=action,
                target_id=None,
                payload=dict(payload),
                expires_at=self._clock.now() + timedelta(seconds=self._session_ttl_seconds),
            )
        )
        return session_id

    @staticmethod
    def _result_item(hit: SearchHit) -> SearchResultItem:
        return SearchResultItem(
            title=hit.title,
            url=hit.url,
            snippet=hit.snippet,
            source_name=hit.source_name,
            thumbnail_url=hit.thumbnail_url,
        )

    @classmethod
    def _encode_hits(cls, hits: tuple[SearchHit, ...]) -> str:
        """Keep pending results bounded in server-side interaction state."""

        return json.dumps(
            [cls._hit_payload(hit) for hit in hits[:20]],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def _encode_history(cls, history: tuple[_SearchState, ...]) -> str:
        return json.dumps(
            [
                {
                    "hit": cls._hit_payload(state.hit),
                    "remaining_hits": json.loads(cls._encode_hits(state.remaining_hits)),
                    "cursor": state.cursor,
                }
                for state in history[-cls._max_history :]
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def _decode_hits(cls, value: str | None) -> tuple[SearchHit, ...]:
        if not value:
            return ()
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return ()
        if not isinstance(decoded, list):
            return ()
        hits: list[SearchHit] = []
        for raw_value in cast(list[object], decoded[:20]):
            hit = cls._decode_hit_object(raw_value)
            if hit is not None:
                hits.append(hit)
        return tuple(hits)

    @classmethod
    def _decode_history(cls, value: str | None) -> tuple[_SearchState, ...]:
        if not value:
            return ()
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return ()
        if not isinstance(decoded, list):
            return ()
        states: list[_SearchState] = []
        for raw_value in cast(list[object], decoded[-cls._max_history :]):
            if not isinstance(raw_value, dict):
                continue
            raw = cast(Mapping[str, object], raw_value)
            hit = cls._decode_hit_object(raw.get("hit"))
            if hit is None:
                continue
            remaining = cls._decode_hits(json.dumps(raw.get("remaining_hits", [])))
            cursor = raw.get("cursor")
            states.append(
                _SearchState(
                    hit=hit,
                    remaining_hits=remaining,
                    cursor=cursor if isinstance(cursor, str) and cursor else None,
                )
            )
        return tuple(states)

    @staticmethod
    def _hit_payload(hit: SearchHit) -> dict[str, object]:
        return {
            "title": hit.title[:300],
            "url": hit.url[:2_048],
            "snippet": hit.snippet[:1_000] if hit.snippet else None,
            "source_name": hit.source_name[:200] if hit.source_name else None,
            "thumbnail_url": hit.thumbnail_url[:2_048] if hit.thumbnail_url else None,
        }

    @classmethod
    def _decode_hit(cls, value: str | None) -> SearchHit | None:
        if not value:
            return None
        try:
            return cls._decode_hit_object(json.loads(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _decode_hit_object(value: object) -> SearchHit | None:
        if not isinstance(value, dict):
            return None
        raw = cast(Mapping[str, object], value)
        title = raw.get("title")
        url = raw.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            return None
        snippet = raw.get("snippet")
        source_name = raw.get("source_name")
        thumbnail_url = raw.get("thumbnail_url")
        return SearchHit(
            title=title[:300],
            url=url[:2_048],
            snippet=snippet[:1_000] if isinstance(snippet, str) else None,
            source_name=source_name[:200] if isinstance(source_name, str) else None,
            thumbnail_url=(
                thumbnail_url[:2_048] if isinstance(thumbnail_url, str) else None
            ),
        )

    @staticmethod
    def _kind(request: ToolRequest, *, session_kind: str | None = None) -> SearchKind:
        if request.capability is CapabilityName.SEARCH_IMAGES:
            return SearchKind.IMAGES
        if request.capability is CapabilityName.SEARCH_GIFS:
            return SearchKind.GIF
        requested = session_kind or request.options.get("kind", SearchKind.WEB.value)
        try:
            return SearchKind(requested)
        except ValueError as error:
            raise InvalidRequest from error

    @staticmethod
    def _error(error_type: type[ToolboxError] | ToolboxError) -> ErrorResult:
        error = error_type() if isinstance(error_type, type) else error_type
        return ErrorResult(code=error.code, message=error.user_message, retryable=error.retryable)
