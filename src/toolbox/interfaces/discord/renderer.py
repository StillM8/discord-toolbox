"""Discord-only presentation for generic Toolbox results."""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import discord

from toolbox.core.contracts import (
    AssetStore,
    Clock,
    PreferencesRepository,
    QuotePreviewService,
    SessionStore,
)
from toolbox.core.models import (
    ActionKind,
    AssetRef,
    CapabilityName,
    ChoiceResult,
    ErrorResult,
    FactCheckResult,
    FileResult,
    HelpResult,
    ImageResult,
    InteractionSession,
    NoAction,
    PendingResult,
    Reminder,
    SavedItem,
    SearchResults,
    TextResult,
    ToolAction,
    ToolResult,
    UserPreferences,
    Visibility,
)
from toolbox.core.result_codec import ResultCodec

from .components import (
    ActionExecutor,
    MessageToolboxView,
    QuoteStyleView,
    SessionActionView,
    UserToolboxView,
)
from .mapper import DiscordMapper


class DiscordRenderer:
    """Turn application results into private previews or public Discord output."""

    def __init__(
        self,
        *,
        sessions: SessionStore | None = None,
        clock: Clock | None = None,
        assets: AssetStore | None = None,
        preferences: PreferencesRepository | None = None,
        quote_preview: QuotePreviewService | None = None,
        mapper: DiscordMapper | None = None,
        codec: ResultCodec | None = None,
        session_ttl_seconds: int = 1_800,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._assets = assets
        self._preferences = preferences
        self._quote_preview = quote_preview
        self._mapper = mapper
        self._codec = codec or ResultCodec()
        self._session_ttl_seconds = session_ttl_seconds
        self._executor: ActionExecutor | None = None

    def bind_executor(self, executor: ActionExecutor) -> None:
        """Bind the one thin bot ingress callback used by component adapters."""

        self._executor = executor

    async def render(self, interaction: Any, result: ToolResult) -> None:
        """Render one normalized result without leaking provider/storage types."""

        if isinstance(result, NoAction):
            return

        preferences = await self._accessibility_preferences(interaction)
        content, embed, file = await self._presentation(result, preferences=preferences)
        if (
            embed is not None
            and preferences is not None
            and preferences.accessibility_high_contrast
        ):
            embed.colour = discord.Colour.from_rgb(255, 255, 255)
        view = await self._action_view(interaction, result)
        kwargs: dict[str, object] = {
            "content": content,
            "ephemeral": not self._is_public(result),
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if embed is not None:
            kwargs["embed"] = embed
        if file is not None:
            kwargs["file"] = file
        if view is not None:
            kwargs["view"] = view

        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)

    async def render_message_toolbox(
        self,
        interaction: Any,
        message: discord.Message,
    ) -> None:
        """Present the thin message-context panel; buttons perform no business work."""

        if self._executor is None:
            await interaction.response.send_message(
                content="Toolbox's message actions are not wired yet.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        view = MessageToolboxView(message, self._executor, self)
        await interaction.response.send_message(
            content="What would you like to do with this message?",
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def render_user_toolbox(
        self,
        interaction: Any,
        user: discord.User | discord.Member,
    ) -> None:
        """Present user actions, including configurable avatar quote cards."""

        if self._executor is None:
            await interaction.response.send_message(
                content="Toolbox's user actions are not wired yet.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        view = UserToolboxView(user, self._executor, self)
        display_name = self._clean(getattr(user, "display_name", "this user"))
        await interaction.response.send_message(
            content=f"What would you like to do with {display_name}?",
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def render_quote_style(
        self,
        interaction: Any,
        *,
        message: discord.Message | None = None,
        user: discord.User | discord.Member | None = None,
    ) -> None:
        """Acknowledge quickly, then show the source image above quote controls."""

        if self._executor is None:
            await interaction.response.send_message(
                content="Quote configuration is not wired yet.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        options = await self._quote_style_options(interaction)
        view = QuoteStyleView(
            self._executor,
            message=message,
            user=user,
            quote_renderer=self,
            initial_values=options,
        )
        embed, file = await self._build_quote_preview(
            interaction,
            message=message,
            user=user,
            options=options,
        )
        kwargs: dict[str, object] = {
            "embed": embed,
            "view": view,
            "ephemeral": True,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if file is not None:
            kwargs["file"] = file
        await interaction.followup.send(**kwargs)

    async def refresh_quote_style(
        self,
        interaction: discord.Interaction,
        *,
        message: discord.Message | None = None,
        user: discord.User | discord.Member | None = None,
        options: Mapping[str, str],
        view: QuoteStyleView,
    ) -> None:
        """Regenerate the local preview and edit the existing ephemeral message."""

        if not interaction.response.is_done():
            # A component acknowledgement of type ``deferred_message_update``
            # keeps the existing preview message as the message edited below.
            await interaction.response.defer()
        embed, file = await self._build_quote_preview(
            interaction,
            message=message,
            user=user,
            options=options,
        )
        if file is not None:
            await interaction.edit_original_response(
                embed=embed,
                attachments=[file],
                view=view,
            )
        else:
            await interaction.edit_original_response(
                embed=embed,
                attachments=[],
                view=view,
            )

    async def _quote_style_options(self, interaction: Any) -> dict[str, str]:
        if self._preferences is None:
            return {
                "font": "sans",
                "text_position": "center",
                "color_mode": "grayscale",
                "image_mode": "left",
            }
        try:
            preferences = await self._preferences.get(int(interaction.user.id))
        except Exception:
            return self._quote_style_options_without_preferences()
        return self._quote_style_options_from_preferences(preferences)

    @staticmethod
    def _quote_style_options_without_preferences() -> dict[str, str]:
        return {
            "font": "sans",
            "text_position": "center",
            "color_mode": "grayscale",
            "image_mode": "left",
        }

    @staticmethod
    def _quote_style_options_from_preferences(
        preferences: UserPreferences,
    ) -> dict[str, str]:
        return {
            "font": preferences.quote_font.value,
            "text_position": preferences.quote_text_position.value,
            "color_mode": preferences.quote_color_mode.value,
            "image_mode": preferences.quote_image_mode.value,
        }

    async def _build_quote_preview(
        self,
        interaction: Any,
        *,
        message: discord.Message | None,
        user: discord.User | discord.Member | None,
        options: Mapping[str, str],
    ) -> tuple[discord.Embed, discord.File | None]:
        embed = discord.Embed(colour=discord.Colour.from_rgb(0, 0, 0))
        if self._quote_preview is not None and self._mapper is not None and message is not None:
            try:
                request = self._mapper.from_interaction(
                    interaction,
                    CapabilityName.QUOTE,
                    target_message=message,
                    target_user=user,
                    options=options,
                )
                data = await self._quote_preview.render_preview(request)
            except Exception:
                data = None
            if data is not None:
                file = discord.File(io.BytesIO(data), filename="quote-preview.png")
                embed.set_image(url="attachment://quote-preview.png")
                return embed, file
        preview_url = self._quote_preview_url(message, user)
        if preview_url is not None:
            embed.set_image(url=preview_url)
        return embed, None

    @classmethod
    def _quote_preview_url(
        cls,
        message: discord.Message | None,
        user: discord.User | discord.Member | None,
    ) -> str | None:
        if message is not None:
            for attachment in message.attachments:
                content_type = (attachment.content_type or "").lower()
                filename = attachment.filename.lower()
                if content_type.startswith("image/") or filename.endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif")
                ):
                    return cls._safe_url(str(attachment.url))
            avatar = getattr(message.author, "display_avatar", None)
            avatar_url = getattr(avatar, "url", None)
            if avatar_url is not None:
                return cls._safe_url(str(avatar_url))
        if user is not None:
            avatar = getattr(user, "display_avatar", None)
            avatar_url = getattr(avatar, "url", None)
            if avatar_url is not None:
                return cls._safe_url(str(avatar_url))
        return None

    async def render_reminder(self, user: Any, reminder: Reminder) -> None:
        """Render a durable reminder as a safe Discord DM notification."""

        await user.send(
            content=f"⏰ Reminder\n{self._clean(reminder.payload)}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def render_saved_item(self, user: Any, item: SavedItem) -> None:
        """Render one owner's saved item as a compact, useful DM bookmark."""

        title = self._clean(item.title) if item.title else "Saved item"
        description = self._clean(item.text) if item.text else "Saved attachment"
        embed = discord.Embed(
            title=f"🔖 {title}",
            description=self._truncate(description, 4_000),
        )
        if item.tags:
            embed.add_field(
                name="Tags",
                value=self._truncate(" ".join(f"#{self._clean(tag)}" for tag in item.tags), 1_000),
                inline=False,
            )
        if item.source_url:
            source = self._safe_url(item.source_url)
            if source:
                embed.add_field(name="Source", value=f"[Open original]({source})", inline=False)
        embed.set_footer(text=f"Toolbox bookmark · {item.item_id}")

        file: discord.File | None = None
        if item.asset_id is not None and self._assets is not None:
            asset = AssetRef(
                asset_id=item.asset_id,
                mime_type=item.asset_mime_type or "application/octet-stream",
                size=item.asset_size or 0,
                owner_id=item.owner_id,
            )
            try:
                data = await self._assets.read(asset)
            except Exception:
                data = None
            if data is not None:
                filename = self._filename(asset.mime_type, "saved-asset")
                file = discord.File(io.BytesIO(data), filename=filename)
                if asset.mime_type.startswith("image/"):
                    embed.set_image(url=f"attachment://{filename}")
        kwargs: dict[str, object] = {
            "embed": embed,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if file is not None:
            kwargs["file"] = file
        await user.send(**kwargs)

    async def _presentation(
        self,
        result: ToolResult,
        *,
        preferences: UserPreferences | None = None,
    ) -> tuple[str | None, discord.Embed | None, discord.File | None]:
        if preferences is not None and preferences.accessibility_plain_text:
            return await self._plain_presentation(result)
        if isinstance(result, HelpResult):
            return None, self._help_embed(result), None
        if isinstance(result, TextResult):
            if result.sources or result.input_text:
                embed = discord.Embed(
                    title=self._clean(result.title) if result.title else None,
                    description=self._truncate(result.text, 4_000),
                )
                if result.input_text:
                    embed.add_field(
                        name="Request",
                        value=self._truncate(self._clean(result.input_text), 1_024),
                        inline=False,
                    )
                source_lines: list[str] = []
                for source in result.sources:
                    url = self._safe_url(source.url)
                    source_lines.append(
                        f"[{self._clean(source.title)}]({url})"
                        if url
                        else self._clean(source.title)
                    )
                embed.add_field(
                    name="Sources",
                    value=self._truncate("\n".join(source_lines), 1_000),
                    inline=False,
                )
                return None, embed, None
            title = f"**{self._clean(result.title)}**\n" if result.title else ""
            return f"{title}{self._truncate(result.text, 3_900)}", None, None
        if isinstance(result, ErrorResult):
            return self._truncate(result.message, 3_900), None, None
        if isinstance(result, SearchResults):
            return (
                None,
                self._search_embed(
                    result,
                    reduce_motion=(
                        preferences.accessibility_reduce_motion if preferences else False
                    ),
                    verbose=(preferences.accessibility_verbose if preferences else False),
                ),
                None,
            )
        if isinstance(result, FactCheckResult):
            return None, self._fact_check_embed(result), None
        if isinstance(result, ChoiceResult):
            embed = discord.Embed(
                title=self._clean(result.title),
                description="\n".join(f"• {self._clean(choice)}" for choice in result.choices),
            )
            return None, embed, None
        if isinstance(result, PendingResult):
            return self._truncate(result.message, 3_900), None, None
        if isinstance(result, ImageResult):
            return await self._image_presentation(result)
        if isinstance(result, FileResult):
            return await self._file_presentation(result)
        raise TypeError(f"Unsupported Toolbox result: {type(result).__name__}")

    async def _accessibility_preferences(self, interaction: Any) -> UserPreferences | None:
        """Load presentation preferences without making rendering depend on storage."""

        if self._preferences is None:
            return None
        try:
            return await self._preferences.get(int(interaction.user.id))
        except Exception:
            return None

    async def _plain_presentation(
        self,
        result: ToolResult,
    ) -> tuple[str | None, discord.Embed | None, discord.File | None]:
        """Render a screen-reader/search-friendly text-first representation."""

        if isinstance(result, HelpResult):
            parts: list[str] = [self._clean(result.title), "All commands are private by default."]
            for section in result.sections:
                parts.append(self._clean(section.title))
                parts.extend(self._clean(line) for line in section.lines)
            return self._truncate("\n\n".join(parts), 3_900), None, None
        if isinstance(result, TextResult):
            parts: list[str] = []
            if result.title:
                parts.append(self._clean(result.title))
            parts.append(self._clean(result.text))
            if result.input_text:
                parts.append(f"Input: {self._clean(result.input_text)}")
            if result.sources:
                parts.append(
                    "Sources:\n"
                    + "\n".join(
                        f"- {self._clean(source.title)}: {self._safe_url(source.url) or source.url}"
                        for source in result.sources
                    )
                )
            return self._truncate("\n\n".join(parts), 3_900), None, None
        if isinstance(result, ErrorResult):
            return self._truncate(self._clean(result.message), 3_900), None, None
        if isinstance(result, SearchResults):
            if not result.items:
                return "No results found.", None, None
            lines = [f"Search results for: {self._clean(result.query)}"]
            for index, item in enumerate(result.items, start=1):
                lines.append(f"{index}. {self._clean(item.title)}")
                lines.append(self._safe_url(item.url) or item.url)
                if item.snippet:
                    lines.append(self._truncate(self._clean(item.snippet), 360))
            return self._truncate("\n".join(lines), 3_900), None, None
        if isinstance(result, FactCheckResult):
            lines = [
                f"Fact check: {self._clean(result.claim)}",
                f"Verdict: {result.verdict.value.replace('_', ' ').title()}",
                self._clean(result.explanation),
            ]
            if result.sources:
                lines.append(
                    "Sources:\n"
                    + "\n".join(
                        f"- {self._clean(source.title)}: {self._safe_url(source.url) or source.url}"
                        for source in result.sources
                    )
                )
            return self._truncate("\n\n".join(lines), 3_900), None, None
        if isinstance(result, ChoiceResult):
            return (
                self._truncate(
                    f"{self._clean(result.title)}\n" + "\n".join(result.choices),
                    3_900,
                ),
                None,
                None,
            )
        if isinstance(result, PendingResult):
            return self._truncate(self._clean(result.message), 3_900), None, None
        if isinstance(result, ImageResult):
            if self._assets is None:
                return "The image is ready, but the asset store is unavailable.", None, None
            data = await self._assets.read(result.asset)
            filename = self._filename(result.asset.mime_type, "toolbox-image")
            file = discord.File(io.BytesIO(data), filename=filename)
            parts = [self._clean(result.title) if result.title else "Image attached."]
            if result.input_text:
                parts.append(f"Request: {self._clean(result.input_text)}")
            return self._truncate("\n\n".join(parts), 3_900), None, file
        if isinstance(result, FileResult):
            if self._assets is None:
                return "The file is ready, but the asset store is unavailable.", None, None
            data = await self._assets.read(result.asset)
            file = discord.File(io.BytesIO(data), filename=self._clean_filename(result.filename))
            parts = [self._clean(result.title) if result.title else result.filename]
            if result.input_text:
                parts.append(f"Request: {self._clean(result.input_text)}")
            return self._truncate("\n\n".join(parts), 3_900), None, file
        raise TypeError(f"Unsupported Toolbox result: {type(result).__name__}")

    async def _image_presentation(
        self,
        result: ImageResult,
    ) -> tuple[str | None, discord.Embed | None, discord.File | None]:
        if self._assets is None:
            return "The image is ready, but the asset store is unavailable.", None, None
        data = await self._assets.read(result.asset)
        filename = self._filename(result.asset.mime_type, "toolbox-image")
        file = discord.File(io.BytesIO(data), filename=filename)
        embed = discord.Embed(title=self._clean(result.title) if result.title else None)
        if result.input_text:
            embed.add_field(
                name="Request",
                value=self._truncate(self._clean(result.input_text), 1_024),
                inline=False,
            )
        embed.set_image(url=f"attachment://{filename}")
        return None, embed, file

    async def _file_presentation(
        self,
        result: FileResult,
    ) -> tuple[str | None, discord.Embed | None, discord.File | None]:
        if self._assets is None:
            return "The file is ready, but the asset store is unavailable.", None, None
        data = await self._assets.read(result.asset)
        file = discord.File(io.BytesIO(data), filename=self._clean_filename(result.filename))
        content_parts: list[str] = []
        if result.title:
            content_parts.append(f"**{self._clean(result.title)}**")
        if result.input_text:
            content_parts.append(
                f"**Request:** {self._truncate(self._clean(result.input_text), 1_000)}"
            )
        content = "\n".join(content_parts) or None
        return content, None, file

    async def _action_view(self, interaction: Any, result: ToolResult) -> discord.ui.View | None:
        if self._sessions is None or self._executor is None or self._is_public(result):
            return None
        actions = self._actions(result)
        owner_id = int(interaction.user.id)
        view = SessionActionView(None, self._executor)
        expires_at = (self._clock.now() if self._clock else datetime.now(UTC)) + timedelta(
            seconds=self._session_ttl_seconds
        )
        for action in actions:
            session_id: UUID | None = None
            capability: CapabilityName | None = None
            payload: Mapping[str, str] | None = None
            if action.kind is ActionKind.SHARE:
                try:
                    payload = self._codec.encode(result)
                except ValueError:
                    continue
                capability = CapabilityName.SHARE
            elif action.kind is ActionKind.SEND_DM and action.target_id is not None:
                payload = {"item_id": str(action.target_id)}
                capability = CapabilityName.SAVED_SEND_DM
            elif isinstance(result, SearchResults) and action.session_id is not None:
                capability = self._search_action_capability(result, action)
                if capability is None:
                    continue
                session_id = action.session_id
            else:
                continue

            if session_id is None:
                session_id = uuid4()
                assert payload is not None
                await self._sessions.create(
                    InteractionSession(
                        session_id=session_id,
                        owner_id=owner_id,
                        action=action.kind,
                        target_id=action.target_id,
                        payload=payload,
                        expires_at=expires_at,
                    )
                )
            view.add_session_action(
                session_id=session_id,
                label=action.label,
                capability=capability,
            )
        return view if view.children else None

    @staticmethod
    def _search_action_capability(
        result: SearchResults,
        action: ToolAction,
    ) -> CapabilityName | None:
        if action.kind is ActionKind.EXPAND:
            return CapabilityName.SEARCH_EXPAND
        if action.kind in {ActionKind.NEXT_PAGE, ActionKind.PREVIOUS_PAGE}:
            if result.kind.value == "images":
                return CapabilityName.SEARCH_IMAGES
            if result.kind.value == "gif":
                return CapabilityName.SEARCH_GIFS
            return CapabilityName.SEARCH_WEB
        return None

    @staticmethod
    def _actions(result: ToolResult) -> Sequence[ToolAction]:
        if isinstance(
            result,
            (
                TextResult,
                SearchResults,
                ImageResult,
                FileResult,
                ChoiceResult,
                FactCheckResult,
                ErrorResult,
            ),
        ):
            return result.actions
        return ()

    @staticmethod
    def _is_public(result: ToolResult) -> bool:
        return getattr(result, "visibility", Visibility.PRIVATE) is Visibility.PUBLIC

    @staticmethod
    def _search_embed(
        result: SearchResults,
        *,
        reduce_motion: bool = False,
        verbose: bool = False,
    ) -> discord.Embed:
        item = result.items[0] if result.items else None
        if item is None:
            description = "No results found."
        else:
            title = DiscordRenderer._clean(item.title)
            url = DiscordRenderer._safe_url(item.url)
            heading = f"[{title}]({url})" if url else title
            if result.kind.value in {"images", "gif"}:
                description = f"**{heading}**"
                if item.source_name:
                    description += f"\n{DiscordRenderer._clean(item.source_name)}"
            else:
                preview = DiscordRenderer._truncate(
                    DiscordRenderer._clean(item.snippet),
                    360,
                )
                description = f"**{heading}**"
                if preview:
                    description += f"\n{preview}"
                if item.source_name:
                    description += f"\n*{DiscordRenderer._clean(item.source_name)}*"
            if verbose:
                description += f"\nURL: {DiscordRenderer._safe_url(item.url) or item.url}"
        embed = discord.Embed(
            title=f"🔎 {DiscordRenderer._clean(result.query)}",
            description=DiscordRenderer._truncate(description, 4_000),
        )
        if result.kind.value in {"images", "gif"}:
            preview = next(
                (
                    DiscordRenderer._safe_url(item.thumbnail_url)
                    for item in result.items
                    if item.thumbnail_url
                ),
                None,
            )
            if preview is not None and not reduce_motion:
                embed.set_image(url=preview)
        footer: list[str] = []
        if any(action.kind is ActionKind.EXPAND for action in result.actions):
            footer.append("Expand for a little more")
        if any(action.kind is ActionKind.PREVIOUS_PAGE for action in result.actions):
            footer.append("Back")
        if any(action.kind is ActionKind.NEXT_PAGE for action in result.actions):
            footer.append("Next result")
        if footer:
            embed.set_footer(text=" · ".join(footer))
        return embed

    @staticmethod
    def _help_embed(result: HelpResult) -> discord.Embed:
        """Render every help section without relying on Discord message length."""

        embed = discord.Embed(
            title=DiscordRenderer._clean(result.title),
            description="All commands are private by default. Use Share to post a result.",
        )
        for section in result.sections:
            value = "\n".join(DiscordRenderer._clean(line) for line in section.lines)
            embed.add_field(
                name=DiscordRenderer._clean(section.title),
                value=DiscordRenderer._truncate(value, 1_024) or "No commands listed.",
                inline=False,
            )
        return embed

    @staticmethod
    def _fact_check_embed(result: FactCheckResult) -> discord.Embed:
        embed = discord.Embed(
            title=f"Fact check: {DiscordRenderer._clean(result.claim)}",
            description=DiscordRenderer._clean(result.explanation),
        )
        embed.add_field(name="Verdict", value=result.verdict.value.replace("_", " ").title())
        if result.sources:
            source_lines: list[str] = []
            for source in result.sources:
                url = DiscordRenderer._safe_url(source.url)
                source_lines.append(
                    f"[{DiscordRenderer._clean(source.title)}]({url})"
                    if url
                    else DiscordRenderer._clean(source.title)
                )
            embed.add_field(
                name="Sources",
                value=DiscordRenderer._truncate("\n".join(source_lines), 1_000),
                inline=False,
            )
        return embed

    @staticmethod
    def _safe_url(value: str) -> str | None:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None

    @staticmethod
    def _filename(mime_type: str, stem: str) -> str:
        extension = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }.get(mime_type, ".bin")
        return f"{stem}{extension}"

    @staticmethod
    def _clean(value: str | None) -> str:
        if not value:
            return ""
        return value.replace("@everyone", "@ everyone").replace("@here", "@ here")

    @staticmethod
    def _clean_filename(value: str) -> str:
        cleaned = value.replace("/", "_").replace("\\", "_").strip()
        return cleaned[:100] or "toolbox-file.bin"

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        return value if len(value) <= limit else f"{value[: limit - 1]}…"
