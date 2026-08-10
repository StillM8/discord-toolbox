"""Reusable, data-driven Discord dashboards for Toolbox entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import discord

from toolbox.core.models import CapabilityName, HelpResult

from .components import (
    ActionExecutor,
    AskMessageModal,
    CaptionModal,
    ImageInstructionModal,
    MemeModal,
    QuotePanelRenderer,
    QuoteStyleView,
)

TOOLBOX_COLOUR: Final[discord.Colour] = discord.Colour.from_rgb(88, 101, 242)


@dataclass(frozen=True, slots=True)
class DashboardAction:
    """One UI action description; it contains routing metadata, not business logic."""

    key: str
    label: str
    description: str
    capability: CapabilityName
    emoji: str
    input_label: str | None = None
    modal_title: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    special: str | None = None


@dataclass(frozen=True, slots=True)
class DashboardCategory:
    """One dashboard tab that can be extended without changing the view shell."""

    key: str
    label: str
    description: str


_CATEGORIES: Final[tuple[DashboardCategory, ...]] = (
    DashboardCategory("home", "Overview", "Quick actions and the Toolbox home screen."),
    DashboardCategory("understand", "Ask and understand", "Ask, translate, explain, or verify."),
    DashboardCategory("search", "Search", "Search the web, images, news, video, or GIFs."),
    DashboardCategory("create", "Create and transform", "Make images, QR codes, memes, and more."),
    DashboardCategory("tools", "Utilities", "Fast deterministic tools for everyday tasks."),
    DashboardCategory("personal", "Personal", "Your saved items, reminders, and preferences."),
    DashboardCategory(
        "selected", "Selected content", "Actions for the message or user you selected."
    ),
)


class DashboardInputModal(discord.ui.Modal):
    """Collect one bounded input before dispatching a dashboard action."""

    def __init__(
        self,
        action: DashboardAction,
        executor: ActionExecutor,
        *,
        target_message: discord.Message | None,
        target_user: discord.User | discord.Member | None,
    ) -> None:
        super().__init__(title=action.modal_title or action.label)
        self._input: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
            label=action.input_label or "Input",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2_000,
        )
        self.add_item(self._input)
        self._action = action
        self._executor = executor
        self._target_message = target_message
        self._target_user = target_user

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self._target_message is not None:
            await self._executor(
                interaction,
                self._action.capability,
                target_message=self._target_message,
                text=str(self._input.value),
                options=dict(self._action.options),
            )
            return
        if self._target_user is not None:
            await self._executor(
                interaction,
                self._action.capability,
                target_user=self._target_user,
                text=str(self._input.value),
                options=dict(self._action.options),
            )
            return
        await self._executor(
            interaction,
            self._action.capability,
            text=str(self._input.value),
            options=dict(self._action.options),
        )


class DashboardCategorySelect(discord.ui.Select[discord.ui.View]):
    """Switch dashboard tabs without entering application behavior."""

    def __init__(self, owner: ToolboxDashboardView) -> None:
        options = [
            discord.SelectOption(
                label=category.label,
                value=category.key,
                description=category.description[:100],
                emoji=_category_emoji(category.key),
                default=category.key == owner.category,
            )
            for category in owner.categories
        ]
        super().__init__(
            placeholder="Choose a Toolbox section",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._owner.select_category(interaction, self.values[0])


class DashboardActionSelect(discord.ui.Select[discord.ui.View]):
    """Choose one action from the selected dashboard category."""

    def __init__(self, owner: ToolboxDashboardView, actions: tuple[DashboardAction, ...]) -> None:
        options = [
            discord.SelectOption(
                label=action.label,
                value=action.key,
                description=action.description[:100],
                emoji=action.emoji,
            )
            for action in actions
        ]
        super().__init__(
            placeholder="Choose an action",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._owner.activate_action(interaction, self.values[0])


class DashboardBackButton(discord.ui.Button[discord.ui.View]):
    """Return to the dashboard home category."""

    def __init__(self, owner: ToolboxDashboardView) -> None:
        super().__init__(label="Back", emoji="◀️", style=discord.ButtonStyle.secondary, row=2)
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._owner.select_category(interaction, "home")


class DashboardCloseButton(discord.ui.Button[discord.ui.View]):
    """Close an ephemeral dashboard without invoking application behavior."""

    def __init__(self, owner: ToolboxDashboardView) -> None:
        super().__init__(label="Close", emoji="❌", style=discord.ButtonStyle.secondary, row=2)
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        del self._owner
        await interaction.response.edit_message(
            content="Toolbox closed.",
            embed=None,
            view=None,
        )


class ToolboxDashboardView(discord.ui.View):
    """A compact dashboard shared by slash, message, and user entry points.

    The shell is intentionally data-driven: adding a capability means adding a
    ``DashboardAction`` to a category, not creating another bespoke Discord view.
    """

    def __init__(
        self,
        executor: ActionExecutor,
        *,
        target_message: discord.Message | None = None,
        target_user: discord.User | discord.Member | None = None,
        quote_renderer: QuotePanelRenderer | None = None,
        high_contrast: bool = False,
    ) -> None:
        super().__init__(timeout=600)
        if target_message is not None and target_user is not None:
            raise ValueError("dashboard cannot target both a message and a user")
        self._executor = executor
        self._target_message = target_message
        self._target_user = target_user
        self._quote_renderer = quote_renderer
        self._high_contrast = high_contrast
        self._categories = self._available_categories()
        self._category = (
            "selected" if target_message is not None or target_user is not None else "home"
        )
        self._action_select: DashboardActionSelect | None = None
        self.add_item(DashboardCategorySelect(self))
        self._back_button = DashboardBackButton(self)
        self._close_button = DashboardCloseButton(self)
        self.add_item(self._back_button)
        self.add_item(self._close_button)
        self._sync_action_select()

    @property
    def category(self) -> str:
        return self._category

    @property
    def categories(self) -> tuple[DashboardCategory, ...]:
        return self._categories

    def embed(self) -> discord.Embed:
        category = next(item for item in self._categories if item.key == self._category)
        context = self._context_description()
        description = f"{context}\n\n{category.description}\n\nChoose an action below."
        embed = discord.Embed(
            title="🧰 Toolbox",
            description=_truncate(description, 4_000),
            colour=(
                discord.Colour.from_rgb(255, 255, 255) if self._high_contrast else TOOLBOX_COLOUR
            ),
        )
        if self._target_message is not None:
            content = _clean(getattr(self._target_message, "content", ""))
            if content:
                embed.add_field(
                    name="Selected message",
                    value=_truncate(content, 900),
                    inline=False,
                )
        elif self._target_user is not None:
            name = _clean(getattr(self._target_user, "display_name", "Selected user"))
            embed.add_field(name="Selected user", value=name, inline=False)
        embed.set_footer(text=f"{category.label} • private Toolbox panel")
        return embed

    async def select_category(self, interaction: discord.Interaction, category: str) -> None:
        if category not in {item.key for item in self._categories}:
            return
        self._category = category
        self._sync_category_select()
        self._sync_action_select()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def activate_action(self, interaction: discord.Interaction, key: str) -> None:
        action = next((item for item in self._actions() if item.key == key), None)
        if action is None:
            await interaction.response.edit_message(
                content="That Toolbox action is no longer available.",
                embed=None,
                view=None,
            )
            return
        if action.special == "ask_message" and self._target_message is not None:
            await interaction.response.send_modal(
                AskMessageModal(self._target_message, self._executor)
            )
            return
        if action.special == "image_instruction" and self._target_message is not None:
            await interaction.response.send_modal(
                ImageInstructionModal(
                    self._target_message,
                    self._executor,
                    capability=action.capability,
                    title=action.modal_title or action.label,
                    options=dict(action.options),
                )
            )
            return
        if action.special == "meme" and self._target_message is not None:
            await interaction.response.send_modal(MemeModal(self._target_message, self._executor))
            return
        if action.special == "caption" and self._target_message is not None:
            await interaction.response.send_modal(
                CaptionModal(self._target_message, self._executor)
            )
            return
        if action.special == "quote":
            if self._quote_renderer is not None:
                await self._quote_renderer.render_quote_style(
                    interaction,
                    message=self._target_message,
                    user=self._target_user,
                )
                return
            await interaction.response.send_message(
                content="Quote configuration",
                view=QuoteStyleView(
                    self._executor,
                    message=self._target_message,
                    user=self._target_user,
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        if action.input_label is not None:
            await interaction.response.send_modal(
                DashboardInputModal(
                    action,
                    self._executor,
                    target_message=self._target_message,
                    target_user=self._target_user,
                )
            )
            return
        if self._target_message is not None:
            await self._executor(
                interaction,
                action.capability,
                target_message=self._target_message,
                options=dict(action.options),
            )
            return
        if self._target_user is not None:
            await self._executor(
                interaction,
                action.capability,
                target_user=self._target_user,
                options=dict(action.options),
            )
            return
        await self._executor(
            interaction,
            action.capability,
            options=dict(action.options),
        )

    def _available_categories(self) -> tuple[DashboardCategory, ...]:
        if self._target_message is not None or self._target_user is not None:
            return tuple(
                item for item in _CATEGORIES if item.key in {"selected", "home", "personal"}
            )
        return tuple(item for item in _CATEGORIES if item.key != "selected")

    def _sync_category_select(self) -> None:
        for child in self.children:
            if isinstance(child, DashboardCategorySelect):
                self.remove_item(child)
                break
        self.add_item(DashboardCategorySelect(self))

    def _sync_action_select(self) -> None:
        if self._action_select is not None:
            self.remove_item(self._action_select)
            self._action_select = None
        actions = self._actions()
        if actions:
            self._action_select = DashboardActionSelect(self, actions)
            self.add_item(self._action_select)
        self._back_button.disabled = self._category == "home"

    def _actions(self) -> tuple[DashboardAction, ...]:
        if self._target_message is not None:
            return (
                _message_actions(self._target_message)
                if self._category == "selected"
                else _personal_actions()
            )
        if self._target_user is not None:
            return _user_actions() if self._category == "selected" else _personal_actions()
        return _category_actions(self._category)

    def _context_description(self) -> str:
        if self._target_message is not None:
            return "Working with the message you selected."
        if self._target_user is not None:
            return "Working with the user you selected."
        return "A private utility panel for search, AI, creation, and everyday tools."


class HelpSectionSelect(discord.ui.Select[discord.ui.View]):
    """Jump between help sections without sending a wall of commands."""

    def __init__(self, owner: HelpView) -> None:
        options = [
            discord.SelectOption(
                label=_clean(section.title)[:100],
                value=str(index),
                default=index == owner.page,
            )
            for index, section in enumerate(owner.sections)
        ]
        super().__init__(
            placeholder="Choose a help section",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )
        self._owner = owner

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._owner.select_page(interaction, int(self.values[0]))


class HelpPageButton(discord.ui.Button[discord.ui.View]):
    """Navigate one help page."""

    def __init__(self, owner: HelpView, *, direction: int) -> None:
        label = "Previous" if direction < 0 else "Next"
        emoji = "◀️" if direction < 0 else "▶️"
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self._owner = owner
        self._direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._owner.select_page(interaction, self._owner.page + self._direction)


class HelpCloseButton(discord.ui.Button[discord.ui.View]):
    """Close the interactive help panel."""

    def __init__(self) -> None:
        super().__init__(label="Close", emoji="❌", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="Help closed.", embed=None, view=None)


class HelpView(discord.ui.View):
    """Paginated help shell that remains usable as command sections grow."""

    def __init__(self, result: HelpResult) -> None:
        super().__init__(timeout=600)
        self.sections = result.sections
        self._title = result.title
        self.page = 0
        self._select = HelpSectionSelect(self)
        self._previous = HelpPageButton(self, direction=-1)
        self._next = HelpPageButton(self, direction=1)
        self.add_item(self._select)
        self.add_item(self._previous)
        self.add_item(self._next)
        self.add_item(HelpCloseButton())
        self._sync_buttons()

    def embed(self) -> discord.Embed:
        section = self.sections[self.page]
        value = "\n".join(_clean(line) for line in section.lines)
        embed = discord.Embed(
            title=f"🧰 {self._title}",
            description=(
                "Use the section menu to browse Toolbox without scrolling through a wall of text."
            ),
            colour=TOOLBOX_COLOUR,
        )
        embed.add_field(
            name=_clean(section.title),
            value=_truncate(value, 1_024) or "No commands listed.",
            inline=False,
        )
        embed.set_footer(text=f"Section {self.page + 1} of {len(self.sections)} • private help")
        return embed

    async def select_page(self, interaction: discord.Interaction, page: int) -> None:
        self.page = max(0, min(page, len(self.sections) - 1))
        self._sync_select()
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    def _sync_select(self) -> None:
        self.remove_item(self._select)
        self._select = HelpSectionSelect(self)
        self.add_item(self._select)

    def _sync_buttons(self) -> None:
        self._previous.disabled = self.page == 0
        self._next.disabled = self.page == len(self.sections) - 1


def _category_actions(category: str) -> tuple[DashboardAction, ...]:
    if category == "home":
        return (
            _input_action(
                "ask",
                "Ask anything",
                "Ask Codex a question.",
                CapabilityName.ASK,
                "Question",
                "Ask Toolbox",
                "❓",
            ),
            _input_action(
                "search",
                "Search the web",
                "Find one result at a time.",
                CapabilityName.SEARCH_WEB,
                "Search query",
                "Search",
                "🔎",
                (("kind", "web"),),
            ),
            _input_action(
                "image",
                "Create an image",
                "Generate an image with Codex ImageGen.",
                CapabilityName.IMAGE_GENERATE,
                "Image prompt",
                "Create image",
                "🎨",
            ),
            _input_action(
                "calc",
                "Calculate",
                "Safely calculate an expression.",
                CapabilityName.CALCULATE,
                "Expression",
                "Calculator",
                "🧮",
            ),
            _direct_action(
                "saved",
                "Saved items",
                "Open your private bookmark vault.",
                CapabilityName.SAVED_SEARCH,
                "🔖",
            ),
        )
    if category == "understand":
        return (
            _input_action(
                "ask",
                "Ask",
                "Ask a question with explicit context.",
                CapabilityName.ASK,
                "Question",
                "Ask Toolbox",
                "❓",
            ),
            _input_action(
                "translate",
                "Translate",
                "Translate text into English.",
                CapabilityName.TRANSLATE,
                "Text to translate",
                "Translate",
                "🌐",
                (("language", "English"),),
            ),
            _input_action(
                "what",
                "What is this?",
                "Explain a term, phrase, or claim.",
                CapabilityName.WHAT_IS_THIS,
                "Subject",
                "What is this?",
                "💡",
            ),
            _input_action(
                "factcheck",
                "Fact check",
                "Search sources and check a claim.",
                CapabilityName.FACT_CHECK,
                "Claim",
                "Fact check",
                "✅",
            ),
            _input_action(
                "research",
                "Research",
                "Search sources and synthesize an answer.",
                CapabilityName.RESEARCH,
                "Question",
                "Research",
                "📚",
            ),
        )
    if category == "search":
        return (
            _input_action(
                "web",
                "Web",
                "Search one web result at a time.",
                CapabilityName.SEARCH_WEB,
                "Search query",
                "Web search",
                "🔎",
                (("kind", "web"),),
            ),
            _input_action(
                "images",
                "Images",
                "Browse image results one at a time.",
                CapabilityName.SEARCH_IMAGES,
                "Image query",
                "Image search",
                "🖼️",
                (("kind", "images"),),
            ),
            _input_action(
                "news",
                "News",
                "Search current news sources.",
                CapabilityName.SEARCH_WEB,
                "News query",
                "News search",
                "📰",
                (("kind", "news"),),
            ),
            _input_action(
                "video",
                "Video",
                "Search video results.",
                CapabilityName.SEARCH_WEB,
                "Video query",
                "Video search",
                "🎬",
                (("kind", "video"),),
            ),
            _input_action(
                "gifs",
                "GIFs",
                "Search animated reactions when enabled.",
                CapabilityName.SEARCH_GIFS,
                "GIF query",
                "GIF search",
                "🎞️",
                (("kind", "gifs"),),
            ),
        )
    if category == "create":
        return (
            _input_action(
                "image",
                "Generate image",
                "Create an image with Codex.",
                CapabilityName.IMAGE_GENERATE,
                "Image prompt",
                "Create image",
                "🎨",
            ),
            _input_action(
                "qr",
                "Make QR code",
                "Turn text or a URL into a QR code.",
                CapabilityName.QR,
                "Text or URL",
                "Create QR code",
                "🔳",
            ),
        )
    if category == "tools":
        return (
            _direct_action(
                "coin",
                "Flip a coin",
                "Get heads or tails instantly.",
                CapabilityName.RANDOM,
                "🪙",
                (("mode", "coin"),),
            ),
            _input_action(
                "text_count",
                "Count text",
                "Count characters, words, and lines.",
                CapabilityName.TEXT,
                "Text",
                "Count text",
                "🔢",
                (("mode", "count"),),
            ),
            _input_action(
                "hash",
                "Hash text",
                "Create a SHA-256 checksum.",
                CapabilityName.ENCODE,
                "Text",
                "Hash text",
                "#️⃣",
                (("mode", "hash"), ("algorithm", "sha256")),
            ),
            _input_action(
                "json",
                "Format JSON",
                "Pretty-print JSON locally.",
                CapabilityName.JSON,
                "JSON text",
                "Format JSON",
                "📋",
                (("mode", "format"),),
            ),
            _input_action(
                "color",
                "Inspect color",
                "Read HEX, RGB, and HSL values.",
                CapabilityName.COLOR,
                "Color",
                "Inspect color",
                "🎨",
                (("mode", "inspect"),),
            ),
            _direct_action(
                "timestamp_now",
                "Timestamp now",
                "Create a Discord timestamp for now.",
                CapabilityName.TIMESTAMP,
                "🕒",
                (("mode", "now"),),
            ),
            _input_action(
                "calc",
                "Calculate",
                "Safely calculate an expression.",
                CapabilityName.CALCULATE,
                "Expression",
                "Calculator",
                "🧮",
            ),
            _input_action(
                "convert",
                "Convert",
                "Convert units, time, or currency.",
                CapabilityName.CONVERT,
                "Conversion",
                "Convert",
                "🔄",
            ),
            _input_action(
                "time",
                "Time",
                "Find the current time in a place.",
                CapabilityName.TIME,
                "Places",
                "Time",
                "🕒",
                (("expression", ""),),
            ),
            _input_action(
                "weather",
                "Weather",
                "Get current weather for a place.",
                CapabilityName.WEATHER,
                "Location",
                "Weather",
                "🌦️",
            ),
        )
    if category == "personal":
        return _personal_actions()
    return ()


def _message_actions(message: discord.Message) -> tuple[DashboardAction, ...]:
    actions = [
        DashboardAction(
            "ask",
            "Ask about it",
            "Ask a question about this message.",
            CapabilityName.ASK,
            "❓",
            special="ask_message",
        ),
        _direct_action(
            "what",
            "What is this?",
            "Explain the selected content.",
            CapabilityName.WHAT_IS_THIS,
            "💡",
        ),
        _direct_action(
            "search",
            "Search it",
            "Search the selected message.",
            CapabilityName.SEARCH_WEB,
            "🔎",
            (("kind", "web"),),
        ),
        _direct_action(
            "translate",
            "Translate",
            "Translate the selected message.",
            CapabilityName.TRANSLATE,
            "🌐",
            (("language", "English"),),
        ),
        _direct_action(
            "factcheck",
            "Fact check",
            "Check the selected claim online.",
            CapabilityName.FACT_CHECK,
            "✅",
        ),
        _direct_action(
            "context",
            "Add to context",
            "Keep it for a later AI question.",
            CapabilityName.CONTEXT_ADD,
            "🧩",
        ),
        _direct_action("save", "Save", "Save it to your private vault.", CapabilityName.SAVE, "🔖"),
        DashboardAction(
            "quote",
            "Make a quote",
            "Build a configurable quote card.",
            CapabilityName.QUOTE,
            "💬",
            special="quote",
        ),
    ]
    content = str(getattr(message, "content", ""))
    if "http://" in content or "https://" in content:
        actions.insert(
            5,
            _direct_action(
                "link",
                "Summarize link",
                "Read and summarize a safe web link.",
                CapabilityName.LINK_SUMMARIZE,
                "🔗",
            ),
        )
    if getattr(message, "attachments", ()):
        actions.extend(
            [
                _direct_action(
                    "image_ask",
                    "Ask about image",
                    "Understand the selected image.",
                    CapabilityName.IMAGE_ASK,
                    "👁️",
                ),
                DashboardAction(
                    "image_edit_ai",
                    "Edit with AI",
                    "Describe a semantic image change.",
                    CapabilityName.IMAGE_EDIT_AI,
                    "✨",
                    special="image_instruction",
                    modal_title="Edit image with AI",
                ),
                _direct_action(
                    "background",
                    "Remove background",
                    "Create a transparent cutout.",
                    CapabilityName.IMAGE_BACKGROUND_REMOVE,
                    "✂️",
                ),
                _direct_action(
                    "ocr",
                    "Extract text",
                    "Read text from the selected image.",
                    CapabilityName.IMAGE_OCR,
                    "🔤",
                ),
                _direct_action(
                    "fileinfo",
                    "File info",
                    "Inspect the selected attachment metadata.",
                    CapabilityName.FILE_INFO,
                    "📄",
                ),
                _direct_action(
                    "deepfry",
                    "Deep fry",
                    "Apply a fast local image effect.",
                    CapabilityName.IMAGE_EDIT,
                    "🔥",
                    (("operation", "deepfry"),),
                ),
                DashboardAction(
                    "caption",
                    "Add caption",
                    "Place a caption above the image.",
                    CapabilityName.IMAGE_CAPTION,
                    "✍",
                    special="caption",
                ),
                DashboardAction(
                    "meme",
                    "Make meme",
                    "Add top, bottom, and caption text.",
                    CapabilityName.IMAGE_MEME,
                    "😂",
                    special="meme",
                ),
                _direct_action(
                    "transcribe",
                    "Transcribe audio",
                    "Transcribe an attached audio file.",
                    CapabilityName.TRANSCRIBE,
                    "🎙",
                ),
            ]
        )
    return tuple(actions)


def _user_actions() -> tuple[DashboardAction, ...]:
    return (
        _direct_action(
            "info",
            "User info",
            "View the information Discord provides.",
            CapabilityName.USER_INFO,
            "👤",
        ),
        DashboardAction(
            "quote",
            "Quote avatar",
            "Build a quote card from this avatar.",
            CapabilityName.QUOTE,
            "💬",
            special="quote",
        ),
    )


def _personal_actions() -> tuple[DashboardAction, ...]:
    return (
        _direct_action(
            "saved",
            "Saved items",
            "Search your private bookmark vault.",
            CapabilityName.SAVED_SEARCH,
            "🔖",
        ),
        _direct_action(
            "reminders",
            "Reminders",
            "View your active reminders.",
            CapabilityName.REMINDER_LIST,
            "⏰",
        ),
        _direct_action(
            "preferences",
            "Preferences",
            "View your Toolbox preferences.",
            CapabilityName.PREFERENCES,
            "⚙",
        ),
        _direct_action(
            "context",
            "Context basket",
            "View explicitly selected AI context.",
            CapabilityName.CONTEXT_LIST,
            "🧩",
        ),
    )


def _direct_action(
    key: str,
    label: str,
    description: str,
    capability: CapabilityName,
    emoji: str,
    options: tuple[tuple[str, str], ...] = (),
) -> DashboardAction:
    return DashboardAction(
        key=key,
        label=label,
        description=description,
        capability=capability,
        emoji=emoji,
        options=options,
    )


def _input_action(
    key: str,
    label: str,
    description: str,
    capability: CapabilityName,
    input_label: str,
    modal_title: str,
    emoji: str,
    options: tuple[tuple[str, str], ...] = (),
) -> DashboardAction:
    return DashboardAction(
        key=key,
        label=label,
        description=description,
        capability=capability,
        emoji=emoji,
        input_label=input_label,
        modal_title=modal_title,
        options=options,
    )


def _category_emoji(category: str) -> str:
    return {
        "home": "🏠",
        "understand": "💡",
        "search": "🔎",
        "create": "🎨",
        "tools": "🛠️",
        "personal": "🔖",
        "selected": "🎯",
    }.get(category, "•")


def _clean(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("@everyone", "@ everyone").replace("@here", "@ here")


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"
