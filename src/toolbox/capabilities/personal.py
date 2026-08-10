"""Owner-scoped context, save, and share capabilities."""

from __future__ import annotations

from uuid import UUID, uuid4

from toolbox.core.actions import send_dm_action
from toolbox.core.contracts import (
    AssetStore,
    AttachmentIngestor,
    Clock,
    ContextStore,
    SavedItemDelivery,
    SavedItemRepository,
    SessionStore,
)
from toolbox.core.errors import InvalidRequest, SessionExpired, ToolboxError
from toolbox.core.models import (
    ActionKind,
    AssetRef,
    ContextItem,
    ErrorResult,
    SavedItem,
    SavedItemKind,
    TextResult,
    ToolRequest,
    ToolResult,
)
from toolbox.core.result_codec import ResultCodec


class ContextAddCapability:
    """Add exactly the selected message/text to the owner's context basket."""

    def __init__(
        self,
        store: ContextStore,
        ingestor: AttachmentIngestor | None = None,
    ) -> None:
        self._store = store
        self._ingestor = ingestor

    async def execute(self, request: ToolRequest) -> ToolResult:
        if request.target_message is None and not request.text:
            return ErrorResult(
                code="invalid_request",
                message="Select a message or provide text first.",
            )
        asset = None
        if request.target_message is not None and request.target_message.attachments:
            if self._ingestor is None:
                return ErrorResult(
                    code="asset_rejected",
                    message="That attachment cannot be added to context yet.",
                )
            try:
                asset = await self._ingestor.ingest(
                    request.target_message.attachments[0],
                    request.actor.user.user_id,
                )
            except ToolboxError as error:
                return ErrorResult(
                    code=error.code,
                    message=error.user_message,
                    retryable=error.retryable,
                )
        item = ContextItem(
            item_id=uuid4(),
            owner_id=request.actor.user.user_id,
            label=(
                f"message by {request.target_message.author_name}"
                if request.target_message
                else "text"
            ),
            text=request.text if request.target_message is None else None,
            message=request.target_message,
            asset=asset,
        )
        await self._store.add(item)
        return TextResult(
            title="Context added",
            text="I added only that selected item to your temporary context basket.",
        )


class ContextClearCapability:
    """Clear one owner's temporary context basket."""

    def __init__(self, store: ContextStore) -> None:
        self._store = store

    async def execute(self, request: ToolRequest) -> ToolResult:
        await self._store.clear(request.actor.user.user_id)
        return TextResult(title="Context cleared", text="Your temporary context basket is empty.")


class ContextListCapability:
    """Show one owner's currently selected temporary context items."""

    def __init__(self, store: ContextStore) -> None:
        self._store = store

    async def execute(self, request: ToolRequest) -> ToolResult:
        items = await self._store.list(request.actor.user.user_id)
        if not items:
            return TextResult(
                title="Context basket",
                text="Your temporary context basket is empty.",
            )
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            detail = item.text
            if detail is None and item.message is not None:
                detail = item.message.content
            if detail is None and item.asset is not None:
                detail = f"{item.asset.mime_type} asset"
            lines.append(f"{index}. {item.label}: {(detail or 'selected item')[:160]}")
        return TextResult(title="Context basket", text="\n".join(lines))


class SaveCapability:
    """Persist an explicit message or text item for one owner."""

    def __init__(
        self,
        repository: SavedItemRepository,
        clock: Clock,
        ingestor: AttachmentIngestor | None = None,
        delivery: SavedItemDelivery | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._ingestor = ingestor
        self._delivery = delivery

    async def execute(self, request: ToolRequest) -> ToolResult:
        text = request.text or (request.target_message.content if request.target_message else "")
        attachment = (
            request.target_message.attachments[0]
            if request.target_message is not None and request.target_message.attachments
            else request.attachments[0] if request.attachments else None
        )
        if not text.strip() and attachment is None:
            return ErrorResult(code="invalid_request", message="There is nothing to save.")

        asset = None
        if attachment is not None:
            if self._ingestor is None:
                return ErrorResult(
                    code="asset_rejected",
                    message="That attachment cannot be saved yet.",
                )
            try:
                asset = await self._ingestor.ingest(
                    attachment,
                    request.actor.user.user_id,
                )
            except ToolboxError as error:
                return ErrorResult(
                    code=error.code,
                    message=error.user_message,
                    retryable=error.retryable,
                )

        tags = _parse_tags(request.options.get("tags", ""))
        title = _bounded_label(
            request.options.get("title")
            or (request.target_message.author_name if request.target_message else None)
        )
        source_url = request.options.get("source_url") or _message_jump_url(
            request.target_message
        )
        item = SavedItem(
            item_id=uuid4(),
            owner_id=request.actor.user.user_id,
            kind=SavedItemKind.MESSAGE if request.target_message else SavedItemKind.TEXT,
            title=title,
            text=text.strip() or None,
            source_url=source_url,
            asset_id=asset.asset_id if asset else None,
            created_at=self._clock.now(),
            tags=tags,
            asset_mime_type=asset.mime_type if asset else None,
            asset_size=asset.size if asset else None,
        )
        await self._repository.save(item)
        sent_to_dm = False
        if request.options.get("send_to_dm", "false").lower() == "true":
            if self._delivery is not None:
                try:
                    await self._delivery.deliver(item)
                    sent_to_dm = True
                except Exception:
                    # Saving is durable; a transient DM failure must not lose it.
                    sent_to_dm = False
            else:
                sent_to_dm = False
        if sent_to_dm:
            message = "Saved privately and sent a copy to your Discord DMs."
            actions = ()
        else:
            message = "Saved privately to your Toolbox vault."
            actions = (send_dm_action(item.item_id),)
        return TextResult(
            title="Saved",
            text=message,
            input_text=text.strip() or None,
            actions=actions,
        )


class SavedSearchCapability:
    """Search only the requesting user's saved items."""

    def __init__(self, repository: SavedItemRepository) -> None:
        self._repository = repository

    async def execute(self, request: ToolRequest) -> ToolResult:
        query = (request.text or request.options.get("query", "")).strip()
        if len(query) > 200:
            return ErrorResult(code="invalid_request", message="Keep the saved-item search short.")
        items = await self._repository.search(request.actor.user.user_id, query)
        if not items:
            return TextResult(title="Saved items", text="No saved items matched that search.")
        lines: list[str] = []
        for item in items[:20]:
            label = item.title or item.text or item.kind.value
            tags = f" · #{' #'.join(item.tags)}" if item.tags else ""
            source = f" · {item.source_url}" if item.source_url else ""
            lines.append(f"`{item.item_id}` · {label[:120]}{tags}{source}")
        return TextResult(title="Saved items", text="\n".join(lines))


class SavedDeleteCapability:
    """Delete one saved item only when it belongs to the actor."""

    def __init__(self, repository: SavedItemRepository, assets: AssetStore | None = None) -> None:
        self._repository = repository
        self._assets = assets

    async def execute(self, request: ToolRequest) -> ToolResult:
        from uuid import UUID

        try:
            item_id = UUID(request.options.get("item_id", ""))
        except ValueError:
            return ErrorResult(code="invalid_request", message="Provide a valid saved-item ID.")
        item = await self._repository.get(request.actor.user.user_id, item_id)
        if item is None:
            return ErrorResult(code="not_found", message="That saved item does not exist for you.")
        await self._repository.delete(request.actor.user.user_id, item_id)
        if item.asset_id is not None and self._assets is not None:
            await self._assets.delete(
                AssetRef(
                    asset_id=item.asset_id,
                    mime_type=item.asset_mime_type or "application/octet-stream",
                    size=item.asset_size or 0,
                    owner_id=item.owner_id,
                )
            )
        return TextResult(title="Saved item deleted", text=f"Deleted `{item_id}` privately.")


class SavedSendDMCapability:
    """Deliver one saved item after re-authorizing its owner and session."""

    def __init__(
        self,
        repository: SavedItemRepository,
        sessions: SessionStore,
        delivery: SavedItemDelivery,
    ) -> None:
        self._repository = repository
        self._sessions = sessions
        self._delivery = delivery

    async def execute(self, request: ToolRequest) -> ToolResult:
        item_id_text = request.options.get("item_id", "").strip()
        session_id = request.session_id
        if session_id is not None:
            session = await self._sessions.get(request.actor.user.user_id, session_id)
            if session is None or session.action is not ActionKind.SEND_DM:
                error = SessionExpired
                return ErrorResult(code=error.code, message=error.user_message)
            item_id_text = session.payload.get("item_id", "")
        try:
            item_id = UUID(item_id_text)
        except ValueError:
            return ErrorResult(code="invalid_request", message="Provide a valid saved-item ID.")
        item = await self._repository.get(request.actor.user.user_id, item_id)
        if item is None:
            return ErrorResult(code="not_found", message="That saved item does not exist for you.")
        try:
            await self._delivery.deliver(item)
        except Exception:
            return ErrorResult(
                code="delivery_failed",
                message="I could not send that saved item to your DMs right now.",
                retryable=True,
            )
        if session_id is not None:
            await self._sessions.delete(request.actor.user.user_id, session_id)
        return TextResult(title="Sent to DM", text="I sent that saved item to your Discord DMs.")


class ShareCapability:
    """Re-authorize and publish a short-lived private result."""

    def __init__(self, sessions: SessionStore, codec: ResultCodec) -> None:
        self._sessions = sessions
        self._codec = codec

    async def execute(self, request: ToolRequest) -> ToolResult:
        if request.session_id is None:
            return ErrorResult(
                code="invalid_request",
                message="That share action is missing its session.",
            )
        if not request.interaction.public_allowed:
            return ErrorResult(
                code="public_response_forbidden",
                message=(
                    "Discord is forcing this external-app response to stay private here. "
                    "In a server, enable **Use External Apps** for your role or channel "
                    "(Server Settings → Roles → Apps Permissions), or use Toolbox in a DM."
                ),
            )
        session = await self._sessions.get(request.actor.user.user_id, request.session_id)
        if session is None or session.action is not ActionKind.SHARE:
            error = SessionExpired
            return ErrorResult(code=error.code, message=error.user_message)
        try:
            result = self._codec.decode(session.payload)
            public_result = self._codec.public(result)
            await self._sessions.delete(request.actor.user.user_id, request.session_id)
            return public_result
        except (KeyError, ValueError, TypeError):
            invalid = InvalidRequest
            return ErrorResult(code=invalid.code, message=invalid.user_message)


def _parse_tags(raw: str) -> tuple[str, ...]:
    """Normalize a small comma-separated tag list at the application boundary."""

    tags: list[str] = []
    for value in raw.split(","):
        tag = " ".join(value.strip().split())
        if not tag:
            continue
        if len(tag) > 32:
            tag = tag[:32]
        if tag.lower() not in {existing.lower() for existing in tags}:
            tags.append(tag)
        if len(tags) == 12:
            break
    return tuple(tags)


def _bounded_label(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.replace("\n", " ").split())[:500] or None


def _message_jump_url(message: object | None) -> str | None:
    """Build a stable Discord jump URL from normalized message coordinates."""

    if message is None:
        return None
    message_id = getattr(message, "message_id", None)
    channel_id = getattr(message, "channel_id", None)
    if message_id is None or channel_id is None:
        return None
    guild_id = getattr(message, "guild_id", None)
    parent = "@me" if guild_id is None else str(guild_id)
    return f"https://discord.com/channels/{parent}/{channel_id}/{message_id}"
