"""Thin Discord component adapters that delegate to the application ingress."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

import discord

from toolbox.core.models import ActionKind, CapabilityName


class ActionExecutor(Protocol):
    """Application-entry callback used by buttons and modals."""

    async def __call__(
        self,
        interaction: discord.Interaction,
        capability: CapabilityName,
        *,
        target_message: discord.Message | None = None,
        target_user: discord.User | discord.Member | None = None,
        source_attachment: discord.Attachment | None = None,
        text: str | None = None,
        options: Mapping[str, str] | None = None,
        session_id: UUID | None = None,
    ) -> None:
        """Forward one UI action to the bot's normalized ingress path."""

        ...


class QuotePanelRenderer(Protocol):
    """Renderer boundary for the quote configuration preview panel."""

    async def render_quote_style(
        self,
        interaction: discord.Interaction,
        *,
        message: discord.Message | None = None,
        user: discord.User | discord.Member | None = None,
    ) -> None:
        """Acknowledge and render one quote configuration panel."""

        ...

    async def refresh_quote_style(
        self,
        interaction: discord.Interaction,
        *,
        message: discord.Message | None = None,
        user: discord.User | discord.Member | None = None,
        options: Mapping[str, str],
        view: QuoteStyleView,
    ) -> None:
        """Regenerate and edit the same quote preview message."""

        ...


class SessionActionButton(discord.ui.Button[discord.ui.View]):
    """A button whose opaque session ID is resolved by the application."""

    def __init__(
        self,
        *,
        session_id: UUID,
        executor: ActionExecutor,
        label: str,
        action_kind: ActionKind = ActionKind.SHARE,
        capability: CapabilityName = CapabilityName.SHARE,
    ) -> None:
        style = {
            ActionKind.SHARE: discord.ButtonStyle.success,
            ActionKind.SEND_DM: discord.ButtonStyle.success,
            ActionKind.EXPAND: discord.ButtonStyle.primary,
            ActionKind.DELETE: discord.ButtonStyle.danger,
        }.get(action_kind, discord.ButtonStyle.secondary)
        emoji = {
            ActionKind.SHARE: "↗",
            ActionKind.SEND_DM: "✉",
            ActionKind.EXPAND: "↕",
            ActionKind.NEXT_PAGE: "▶",
            ActionKind.PREVIOUS_PAGE: "◀",
            ActionKind.REGENERATE: "↻",
            ActionKind.REFINE: "✎",
        }.get(action_kind)
        super().__init__(
            label=label,
            style=style,
            emoji=emoji,
            custom_id=f"tbx:v1:act:{session_id}",
        )
        self._session_id = session_id
        self._executor = executor
        self._capability = capability

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._executor(
            interaction,
            self._capability,
            session_id=self._session_id,
        )


class SessionActionView(discord.ui.View):
    """Render only actions that have already been authorized into session state."""

    def __init__(
        self,
        session_id: UUID | None,
        executor: ActionExecutor,
        *,
        label: str = "Share",
        action_kind: ActionKind = ActionKind.SHARE,
        capability: CapabilityName = CapabilityName.SHARE,
    ) -> None:
        super().__init__(timeout=None)
        self._executor = executor
        if session_id is not None:
            self.add_session_action(
                session_id=session_id,
                label=label,
                action_kind=action_kind,
                capability=capability,
            )

    def add_session_action(
        self,
        *,
        session_id: UUID,
        label: str,
        capability: CapabilityName,
        action_kind: ActionKind = ActionKind.SHARE,
    ) -> None:
        """Add one opaque, already-authorized application action."""

        self.add_item(
            SessionActionButton(
                session_id=session_id,
                executor=self._executor,
                label=label,
                action_kind=action_kind,
                capability=capability,
            )
        )


class AskMessageModal(discord.ui.Modal, title="Ask about this message"):
    """Collect only the user's explicit question before dispatching Ask."""

    question: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="What do you want to know?",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1_000,
    )

    def __init__(self, message: discord.Message, executor: ActionExecutor) -> None:
        super().__init__()
        self._message = message
        self._executor = executor

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._executor(
            interaction,
            CapabilityName.ASK,
            target_message=self._message,
            text=str(self.question.value),
        )


class ImageInstructionModal(discord.ui.Modal):
    """Collect one explicit image instruction before entering the application."""

    instruction: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="What should Toolbox do?",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2_000,
    )

    def __init__(
        self,
        message: discord.Message,
        executor: ActionExecutor,
        *,
        capability: CapabilityName,
        title: str,
        options: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(title=title)
        self._message = message
        self._executor = executor
        self._capability = capability
        self._options = dict(options or {})

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._executor(
            interaction,
            self._capability,
            target_message=self._message,
            text=str(self.instruction.value),
            options=self._options,
        )


class MemeModal(discord.ui.Modal, title="Make a meme"):
    """Collect bounded meme text without putting rendering logic in Discord UI."""

    top: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Top text",
        required=False,
        max_length=200,
    )
    bottom: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Bottom text",
        required=False,
        max_length=200,
    )
    caption: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Caption above image",
        required=False,
        max_length=200,
    )

    def __init__(self, message: discord.Message, executor: ActionExecutor) -> None:
        super().__init__()
        self._message = message
        self._executor = executor

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._executor(
            interaction,
            CapabilityName.IMAGE_MEME,
            target_message=self._message,
            options={
                "operation": "meme",
                "top": str(self.top.value or ""),
                "bottom": str(self.bottom.value or ""),
                "caption": str(self.caption.value or ""),
            },
        )


class CaptionModal(discord.ui.Modal, title="Caption image"):
    """Collect one caption that will be rendered above the selected image."""

    caption: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Caption above image",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=200,
    )

    def __init__(self, message: discord.Message, executor: ActionExecutor) -> None:
        super().__init__()
        self._message = message
        self._executor = executor

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._executor(
            interaction,
            CapabilityName.IMAGE_CAPTION,
            target_message=self._message,
            options={
                "operation": "caption",
                "caption": str(self.caption.value),
            },
        )


class QuoteStyleSelect(discord.ui.Select[discord.ui.View]):
    """One bounded quote-style selector; it only updates ephemeral UI state."""

    def __init__(
        self,
        owner: QuoteStyleView,
        *,
        key: str,
        placeholder: str,
        options: list[discord.SelectOption],
        row: int,
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            row=row,
        )
        self._owner = owner
        self._key = key

    @property
    def key(self) -> str:
        """Expose the bounded option key to the owning view."""

        return self._key

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.set_value(self._key, self.values[0])
        await self._owner.refresh(interaction)


class QuoteGenerateButton(discord.ui.Button[discord.ui.View]):
    """Submit the selected quote style through the normal application ingress."""

    def __init__(self, owner: QuoteStyleView) -> None:
        super().__init__(label="Generate", style=discord.ButtonStyle.primary, row=4)
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._owner.generate(interaction)


class QuoteCancelButton(discord.ui.Button[discord.ui.View]):
    """Close a quote configuration panel without invoking application behavior."""

    def __init__(self, owner: QuoteStyleView) -> None:
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, row=4)
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        del self._owner
        await interaction.response.edit_message(content="Quote cancelled.", view=None)


class QuoteStyleView(discord.ui.View):
    """Ephemeral quote configuration shared by message and user entry points."""

    def __init__(
        self,
        executor: ActionExecutor,
        *,
        message: discord.Message | None = None,
        user: discord.User | discord.Member | None = None,
        quote_renderer: QuotePanelRenderer | None = None,
        initial_values: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(timeout=300)
        if message is None and user is None:
            raise ValueError("quote style view requires a message or user target")
        self._executor = executor
        self._message = message
        self._user = user
        self._quote_renderer = quote_renderer
        self._values: dict[str, str] = {
            "font": "sans",
            "text_position": "center",
            "color_mode": "grayscale",
            "image_mode": "left",
        }
        allowed_values = {
            "font": {"sans", "serif", "mono", "display"},
            "text_position": {"left", "center", "right"},
            "color_mode": {"grayscale", "color"},
            "image_mode": {"left", "right", "background", "hidden"},
        }
        for key, value in (initial_values or {}).items():
            if value in allowed_values.get(key, set()):
                self._values[key] = value
        self.add_item(
            QuoteStyleSelect(
                self,
                key="font",
                placeholder="Font",
                options=[
                    discord.SelectOption(
                        label="Sans", value="sans", default=self._values["font"] == "sans"
                    ),
                    discord.SelectOption(
                        label="Serif", value="serif", default=self._values["font"] == "serif"
                    ),
                    discord.SelectOption(
                        label="Mono", value="mono", default=self._values["font"] == "mono"
                    ),
                    discord.SelectOption(
                        label="Display",
                        value="display",
                        default=self._values["font"] == "display",
                    ),
                ],
                row=0,
            )
        )
        self.add_item(
            QuoteStyleSelect(
                self,
                key="text_position",
                placeholder="Text position",
                options=[
                    discord.SelectOption(
                        label="Left",
                        value="left",
                        default=self._values["text_position"] == "left",
                    ),
                    discord.SelectOption(
                        label="Center",
                        value="center",
                        default=self._values["text_position"] == "center",
                    ),
                    discord.SelectOption(
                        label="Right",
                        value="right",
                        default=self._values["text_position"] == "right",
                    ),
                ],
                row=1,
            )
        )
        self.add_item(
            QuoteStyleSelect(
                self,
                key="color_mode",
                placeholder="Photo color",
                options=[
                    discord.SelectOption(
                        label="Black and white",
                        value="grayscale",
                        default=self._values["color_mode"] == "grayscale",
                    ),
                    discord.SelectOption(
                        label="Color",
                        value="color",
                        default=self._values["color_mode"] == "color",
                    ),
                ],
                row=2,
            )
        )
        self.add_item(
            QuoteStyleSelect(
                self,
                key="image_mode",
                placeholder="Photo placement",
                options=[
                    discord.SelectOption(
                        label="Left",
                        value="left",
                        default=self._values["image_mode"] == "left",
                    ),
                    discord.SelectOption(
                        label="Right",
                        value="right",
                        default=self._values["image_mode"] == "right",
                    ),
                    discord.SelectOption(
                        label="Background",
                        value="background",
                        default=self._values["image_mode"] == "background",
                    ),
                    discord.SelectOption(
                        label="Hidden",
                        value="hidden",
                        default=self._values["image_mode"] == "hidden",
                    ),
                ],
                row=3,
            )
        )
        self.add_item(QuoteGenerateButton(self))
        self.add_item(QuoteCancelButton(self))

    def set_value(self, key: str, value: str) -> None:
        self._values[key] = value
        for child in self.children:
            if not isinstance(child, QuoteStyleSelect) or child.key != key:
                continue
            for option in child.options:
                option.default = option.value == value

    async def refresh(self, interaction: discord.Interaction) -> None:
        if self._quote_renderer is None:
            await interaction.response.edit_message(view=self)
            return
        await self._quote_renderer.refresh_quote_style(
            interaction,
            message=self._message,
            user=self._user,
            options=dict(self._values),
            view=self,
        )

    async def generate(self, interaction: discord.Interaction) -> None:
        await self._executor(
            interaction,
            CapabilityName.QUOTE,
            target_message=self._message,
            target_user=self._user,
            options=self._values,
        )


class MessageActionButton(discord.ui.Button[discord.ui.View]):
    """One message-context action with no business logic in the callback."""

    def __init__(
        self,
        *,
        capability: CapabilityName,
        label: str,
        message: discord.Message,
        executor: ActionExecutor,
        options: Mapping[str, str] | None = None,
        quote_renderer: QuotePanelRenderer | None = None,
    ) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self._capability = capability
        self._message = message
        self._executor = executor
        self._options = dict(options or {})
        self._quote_renderer = quote_renderer

    async def callback(self, interaction: discord.Interaction) -> None:
        if self._capability is CapabilityName.ASK:
            await interaction.response.send_modal(AskMessageModal(self._message, self._executor))
            return
        if self._capability is CapabilityName.IMAGE_EDIT_AI:
            await interaction.response.send_modal(
                ImageInstructionModal(
                    self._message,
                    self._executor,
                    capability=CapabilityName.IMAGE_EDIT_AI,
                    title="Edit image with AI",
                )
            )
            return
        if self._capability is CapabilityName.IMAGE_MEME:
            await interaction.response.send_modal(MemeModal(self._message, self._executor))
            return
        if self._capability is CapabilityName.IMAGE_CAPTION:
            await interaction.response.send_modal(CaptionModal(self._message, self._executor))
            return
        if self._capability is CapabilityName.QUOTE:
            if self._quote_renderer is not None:
                await self._quote_renderer.render_quote_style(
                    interaction,
                    message=self._message,
                )
                return
            await interaction.response.send_message(
                view=QuoteStyleView(
                    self._executor,
                    message=self._message,
                    quote_renderer=self._quote_renderer,
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await self._executor(
            interaction,
            self._capability,
            target_message=self._message,
            options=self._options,
        )


class MessageToolboxView(discord.ui.View):
    """Small context panel shared by message actions."""

    def __init__(
        self,
        message: discord.Message,
        executor: ActionExecutor,
        quote_renderer: QuotePanelRenderer | None = None,
    ) -> None:
        super().__init__(timeout=300)
        actions = [
            (CapabilityName.ASK, "Ask"),
            (CapabilityName.WHAT_IS_THIS, "What is this?"),
            (CapabilityName.SEARCH_WEB, "Search"),
            (CapabilityName.TRANSLATE, "Translate"),
            (CapabilityName.FACT_CHECK, "Fact check"),
            (CapabilityName.QUOTE, "Quote"),
            (CapabilityName.CONTEXT_ADD, "Add context"),
            (CapabilityName.SAVE, "Save"),
        ]
        if "http://" in str(getattr(message, "content", "")) or "https://" in str(
            getattr(message, "content", "")
        ):
            actions.insert(4, (CapabilityName.LINK_SUMMARIZE, "Summarize link"))
        if getattr(message, "attachments", ()):
            actions.extend(
                [
                    (CapabilityName.IMAGE_ASK, "Ask image"),
                    (CapabilityName.IMAGE_EDIT_AI, "Edit AI"),
                    (CapabilityName.IMAGE_BACKGROUND_REMOVE, "Remove bg"),
                    (CapabilityName.IMAGE_OCR, "OCR"),
                    (CapabilityName.IMAGE_EDIT, "Deep fry"),
                    (CapabilityName.IMAGE_CAPTION, "Caption"),
                    (CapabilityName.IMAGE_MEME, "Meme"),
                    (CapabilityName.TRANSCRIBE, "Transcribe"),
                ]
            )
        for capability, label in actions:
            operation = {
                CapabilityName.IMAGE_EDIT: "deepfry",
                CapabilityName.IMAGE_MEME: "meme",
            }.get(capability)
            options = {"operation": operation} if operation is not None else None
            self.add_item(
                MessageActionButton(
                    capability=capability,
                    label=label,
                    message=message,
                    executor=executor,
                    options=options,
                    quote_renderer=quote_renderer,
                )
            )


class UserActionButton(discord.ui.Button[discord.ui.View]):
    """One user-context action that delegates without embedding business logic."""

    def __init__(
        self,
        *,
        capability: CapabilityName,
        label: str,
        user: discord.User | discord.Member,
        executor: ActionExecutor,
        quote_renderer: QuotePanelRenderer | None = None,
    ) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self._capability = capability
        self._user = user
        self._executor = executor
        self._quote_renderer = quote_renderer

    async def callback(self, interaction: discord.Interaction) -> None:
        if self._capability is CapabilityName.QUOTE:
            if self._quote_renderer is not None:
                await self._quote_renderer.render_quote_style(
                    interaction,
                    user=self._user,
                )
                return
            await interaction.response.send_message(
                view=QuoteStyleView(
                    self._executor,
                    user=self._user,
                    quote_renderer=self._quote_renderer,
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await self._executor(
            interaction,
            self._capability,
            target_user=self._user,
        )


class UserToolboxView(discord.ui.View):
    """Small user-context panel, including the configurable quote action."""

    def __init__(
        self,
        user: discord.User | discord.Member,
        executor: ActionExecutor,
        quote_renderer: QuotePanelRenderer | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.add_item(
            UserActionButton(
                capability=CapabilityName.USER_INFO,
                label="User info",
                user=user,
                executor=executor,
                quote_renderer=quote_renderer,
            )
        )
        self.add_item(
            UserActionButton(
                capability=CapabilityName.QUOTE,
                label="Quote avatar",
                user=user,
                executor=executor,
                quote_renderer=quote_renderer,
            )
        )
