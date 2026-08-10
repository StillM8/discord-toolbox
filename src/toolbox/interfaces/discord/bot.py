"""Thin discord.py transport and ingress adapter for Toolbox."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from uuid import UUID

import discord
from discord import app_commands

from toolbox.app.dispatcher import Dispatcher
from toolbox.core.contracts import HealthService
from toolbox.core.models import CapabilityName, ErrorResult, HealthState
from toolbox.infrastructure.logging import log_event

from .mapper import DiscordMapper
from .renderer import DiscordRenderer


class ToolboxBot(discord.Client):
    """Discord adapter that maps interactions into the application."""

    def __init__(
        self,
        *,
        dispatcher: Dispatcher,
        mapper: DiscordMapper,
        renderer: DiscordRenderer,
        health: HealthService | None = None,
    ) -> None:
        intents = discord.Intents.none()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._dispatcher = dispatcher
        self._mapper = mapper
        self._renderer = renderer
        self._health = health
        self._logger = logging.getLogger("toolbox.discord")
        self._renderer.bind_executor(self._execute)

    async def setup_hook(self) -> None:
        """Register thin command/context adapters for the application dispatcher."""

        log_event(self._logger, "discord_setup_hook_started")

        @app_commands.command(name="ping", description="Check whether Toolbox is online.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def ping(interaction: discord.Interaction) -> None:
            await self._execute(interaction, CapabilityName.PING)

        @app_commands.command(name="help", description="Show all Toolbox commands.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def help_command(interaction: discord.Interaction) -> None:
            await self._execute(interaction, CapabilityName.HELP)

        @app_commands.command(name="toolbox", description="Open the private Toolbox dashboard.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def toolbox_dashboard(interaction: discord.Interaction) -> None:
            await self._renderer.render_dashboard(interaction)

        search_modes = [
            app_commands.Choice(name="Web", value="web"),
            app_commands.Choice(name="Images", value="images"),
            app_commands.Choice(name="News", value="news"),
            app_commands.Choice(name="Video", value="video"),
            app_commands.Choice(name="GIFs", value="gifs"),
        ]

        async def execute_search(
            interaction: discord.Interaction,
            query: str,
            mode: app_commands.Choice[str] | None,
        ) -> None:
            mode_value = mode.value if mode is not None else "web"
            capability = (
                CapabilityName.SEARCH_IMAGES
                if mode_value == "images"
                else CapabilityName.SEARCH_GIFS
                if mode_value == "gifs"
                else CapabilityName.SEARCH_WEB
            )
            await self._execute(
                interaction,
                capability,
                text=query,
                options={"kind": mode_value},
            )

        @app_commands.command(name="find", description="Search the web or image results.")
        @app_commands.describe(query="What should Toolbox search for?", mode="Search type")
        @app_commands.choices(mode=search_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def find(
            interaction: discord.Interaction,
            query: str,
            mode: app_commands.Choice[str] | None = None,
        ) -> None:
            await execute_search(interaction, query, mode)

        @app_commands.command(name="search", description="Search the web or image results.")
        @app_commands.describe(query="What should Toolbox search for?", mode="Search type")
        @app_commands.choices(mode=search_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def search(
            interaction: discord.Interaction,
            query: str,
            mode: app_commands.Choice[str] | None = None,
        ) -> None:
            await execute_search(interaction, query, mode)

        @app_commands.command(name="ask", description="Ask Toolbox a question.")
        @app_commands.describe(question="What do you want to know?")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def ask(interaction: discord.Interaction, question: str) -> None:
            await self._execute(interaction, CapabilityName.ASK, text=question)

        @app_commands.command(name="translate", description="Translate text into a language.")
        @app_commands.describe(
            text="Text to translate",
            language="Target language",
            source="Optional source language, e.g. Pashto",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def translate(
            interaction: discord.Interaction,
            text: str,
            language: str = "English",
            source: str | None = None,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.TRANSLATE,
                text=text,
                options={"language": language, "source_language": source or "auto"},
            )

        @app_commands.command(name="what", description="Explain a term, claim, phrase, or link.")
        @app_commands.describe(subject="What should Toolbox explain?")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def what(interaction: discord.Interaction, subject: str) -> None:
            await self._execute(interaction, CapabilityName.WHAT_IS_THIS, text=subject)

        @app_commands.command(
            name="research",
            description="Search sources and synthesize an answer.",
        )
        @app_commands.describe(question="What should Toolbox research?")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def research(interaction: discord.Interaction, question: str) -> None:
            await self._execute(interaction, CapabilityName.RESEARCH, text=question)

        @app_commands.command(name="factcheck", description="Check a claim against web sources.")
        @app_commands.describe(claim="What claim should Toolbox check?")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def factcheck(interaction: discord.Interaction, claim: str) -> None:
            await self._execute(interaction, CapabilityName.FACT_CHECK, text=claim)

        @app_commands.command(name="link", description="Summarize a web page from a URL.")
        @app_commands.describe(url="HTTP or HTTPS URL")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def link(interaction: discord.Interaction, url: str) -> None:
            await self._execute(interaction, CapabilityName.LINK_SUMMARIZE, text=url)

        @app_commands.command(name="time", description="Get the time in one or two places.")
        @app_commands.describe(expression="Examples: UK Islamabad, or 5pm UK Islamabad")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def time_command(interaction: discord.Interaction, expression: str) -> None:
            await self._execute(
                interaction,
                CapabilityName.TIME,
                text=expression,
                options={"expression": expression},
            )

        @app_commands.command(name="remind", description="Create a durable personal reminder.")
        @app_commands.describe(
            when="For example: in 30 minutes, or an ISO UTC timestamp",
            note="Reminder note",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def remind(interaction: discord.Interaction, when: str, note: str) -> None:
            await self._execute(
                interaction,
                CapabilityName.REMINDER_CREATE,
                text=note,
                options={"due_at": when, "payload": note},
            )

        @app_commands.command(name="reminders", description="List your active Toolbox reminders.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def reminders(interaction: discord.Interaction) -> None:
            await self._execute(interaction, CapabilityName.REMINDER_LIST)

        @app_commands.command(name="cancel-reminder", description="Cancel one of your reminders.")
        @app_commands.describe(reminder_id="The ID shown by /reminders")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def cancel_reminder(interaction: discord.Interaction, reminder_id: str) -> None:
            await self._execute(
                interaction,
                CapabilityName.REMINDER_CANCEL,
                options={"reminder_id": reminder_id},
            )

        @app_commands.command(name="saved", description="Search your private saved Toolbox items.")
        @app_commands.describe(query="Text to search for; leave blank to list recent items")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def saved(interaction: discord.Interaction, query: str | None = None) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVED_SEARCH,
                text=query,
                options={"query": query or ""},
            )

        @app_commands.command(name="save", description="Save text or an attachment to your vault.")
        @app_commands.describe(
            text="Text to save",
            title="Optional bookmark title",
            tags="Comma-separated tags, such as idea,read-later",
            send_to_dm="Also send a copy to your Discord DMs",
            attachment="Optional attachment to save",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def save(
            interaction: discord.Interaction,
            text: str = "",
            title: str = "",
            tags: str = "",
            send_to_dm: bool = False,
            attachment: discord.Attachment | None = None,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVE,
                text=text,
                source_attachment=attachment,
                options={
                    "title": title,
                    "tags": tags,
                    "send_to_dm": str(send_to_dm).lower(),
                },
            )

        @app_commands.command(name="bookmark", description="Alias for /save.")
        @app_commands.describe(
            text="Text to bookmark",
            title="Optional bookmark title",
            tags="Comma-separated tags",
            send_to_dm="Also send a copy to your Discord DMs",
            attachment="Optional attachment to bookmark",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def bookmark(
            interaction: discord.Interaction,
            text: str = "",
            title: str = "",
            tags: str = "",
            send_to_dm: bool = False,
            attachment: discord.Attachment | None = None,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVE,
                text=text,
                source_attachment=attachment,
                options={
                    "title": title,
                    "tags": tags,
                    "send_to_dm": str(send_to_dm).lower(),
                },
            )

        @app_commands.command(name="bookmarks", description="Search your saved bookmarks.")
        @app_commands.describe(query="Search text or tags; leave blank for recent bookmarks")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def bookmarks(interaction: discord.Interaction, query: str | None = None) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVED_SEARCH,
                text=query,
                options={"query": query or ""},
            )

        @app_commands.command(name="send-saved", description="Send one saved item to your DMs.")
        @app_commands.describe(item_id="The ID shown by /saved or /bookmarks")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def send_saved(interaction: discord.Interaction, item_id: str) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVED_SEND_DM,
                options={"item_id": item_id},
            )

        @app_commands.command(name="export-bookmarks", description="Download your bookmark vault.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def export_bookmarks(interaction: discord.Interaction) -> None:
            await self._execute(interaction, CapabilityName.SAVED_EXPORT)

        @app_commands.command(name="unsave", description="Delete one private saved Toolbox item.")
        @app_commands.describe(item_id="The ID shown by /saved")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def unsave(interaction: discord.Interaction, item_id: str) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVED_DELETE,
                options={"item_id": item_id},
            )

        me_group = app_commands.Group(
            name="me",
            description="Your private Toolbox data and preferences.",
        )

        @me_group.command(name="preferences", description="View or update your preferences.")
        @app_commands.describe(setting="Preference to update", value="New value")
        @app_commands.choices(
            setting=[
                app_commands.Choice(name="Timezone", value="timezone"),
                app_commands.Choice(name="Language", value="language"),
                app_commands.Choice(name="Currency", value="currency"),
                app_commands.Choice(name="Visibility", value="visibility"),
                app_commands.Choice(name="AI profile", value="profile"),
                app_commands.Choice(name="Plain text", value="plain_text"),
                app_commands.Choice(name="High contrast", value="high_contrast"),
                app_commands.Choice(name="Reduce motion", value="reduce_motion"),
                app_commands.Choice(name="Verbose descriptions", value="verbose"),
            ]
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_preferences(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            setting: app_commands.Choice[str] | None = None,
            value: str | None = None,
        ) -> None:
            options: dict[str, str] = {}
            if setting is not None:
                options["setting"] = setting.value
            if value is not None:
                options["value"] = value
            await self._execute(interaction, CapabilityName.PREFERENCES, options=options)

        accessibility_settings = [
            app_commands.Choice(name="Plain text", value="plain_text"),
            app_commands.Choice(name="High contrast", value="high_contrast"),
            app_commands.Choice(name="Reduce motion", value="reduce_motion"),
            app_commands.Choice(name="Verbose descriptions", value="verbose"),
        ]

        @me_group.command(
            name="accessibility",
            description="Configure screen-reader and presentation preferences.",
        )
        @app_commands.describe(setting="Accessibility setting", value="on or off")
        @app_commands.choices(setting=accessibility_settings)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_accessibility(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            setting: app_commands.Choice[str] | None = None,
            value: str | None = None,
        ) -> None:
            options: dict[str, str] = {}
            if setting is not None:
                options["setting"] = setting.value
            if value is not None:
                options["value"] = value
            await self._execute(interaction, CapabilityName.PREFERENCES, options=options)

        @me_group.command(name="status", description="Show owner-only runtime health.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_status(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
        ) -> None:
            await self._execute(interaction, CapabilityName.STATUS)

        @me_group.command(
            name="codex-login",
            description="Get a private Codex authentication link.",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_codex_login(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
        ) -> None:
            await self._execute(interaction, CapabilityName.CODEX_LOGIN)

        @me_group.command(name="saved", description="Search your private saved items.")
        @app_commands.describe(query="Text to search for; leave blank for recent items")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_saved(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            query: str | None = None,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVED_SEARCH,
                text=query,
                options={"query": query or ""},
            )

        @me_group.command(name="bookmarks", description="Search your private bookmarks.")
        @app_commands.describe(query="Text or tag to search for")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_bookmarks(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            query: str | None = None,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.SAVED_SEARCH,
                text=query,
                options={"query": query or ""},
            )

        @me_group.command(name="export", description="Download your bookmark vault.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_export(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
        ) -> None:
            await self._execute(interaction, CapabilityName.SAVED_EXPORT)

        @me_group.command(name="reminders", description="List your active reminders.")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_reminders(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
        ) -> None:
            await self._execute(interaction, CapabilityName.REMINDER_LIST)

        @me_group.command(
            name="context",
            description="List or clear your temporary context basket.",
        )
        @app_commands.describe(clear="Clear the basket instead of listing it")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def me_context(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            clear: bool = False,
        ) -> None:
            capability = CapabilityName.CONTEXT_CLEAR if clear else CapabilityName.CONTEXT_LIST
            await self._execute(interaction, capability)

        create_group = app_commands.Group(
            name="create",
            description="Generate media and artifacts.",
        )

        quote_fonts = [
            app_commands.Choice(name="Sans", value="sans"),
            app_commands.Choice(name="Serif", value="serif"),
            app_commands.Choice(name="Mono", value="mono"),
            app_commands.Choice(name="Display", value="display"),
        ]
        quote_positions = [
            app_commands.Choice(name="Left", value="left"),
            app_commands.Choice(name="Center", value="center"),
            app_commands.Choice(name="Right", value="right"),
        ]
        quote_colors = [
            app_commands.Choice(name="Black and white", value="grayscale"),
            app_commands.Choice(name="Color", value="color"),
        ]
        quote_images = [
            app_commands.Choice(name="Left", value="left"),
            app_commands.Choice(name="Right", value="right"),
            app_commands.Choice(name="Background", value="background"),
            app_commands.Choice(name="Hidden", value="hidden"),
        ]

        @create_group.command(name="image", description="Generate an image from a prompt.")
        @app_commands.describe(prompt="What should the image contain?")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def create_image(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            prompt: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.IMAGE_GENERATE,
                text=prompt,
                options={"prompt": prompt},
            )

        @create_group.command(name="meme", description="Caption an attached image.")
        @app_commands.describe(
            attachment="Image to caption",
            top="Optional top caption",
            bottom="Optional bottom caption",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def create_meme(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
            top: str = "",
            bottom: str = "",
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.IMAGE_MEME,
                source_attachment=attachment,
                options={"operation": "meme", "top": top, "bottom": bottom},
            )

        @create_group.command(name="caption", description="Add a caption above an image.")
        @app_commands.describe(
            attachment="Image to caption",
            caption="Text to place above the image",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def create_caption(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
            caption: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.IMAGE_CAPTION,
                source_attachment=attachment,
                options={"operation": "caption", "caption": caption},
            )

        @create_group.command(name="quote", description="Make a quote card from an image.")
        @app_commands.describe(
            attachment="Image to use",
            quote="Quote text",
            author="Optional attribution",
            font="Quote font",
            position="Text alignment",
            color="Photo color",
            image="Photo placement",
        )
        @app_commands.choices(
            font=quote_fonts,
            position=quote_positions,
            color=quote_colors,
            image=quote_images,
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def create_quote(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
            quote: str,
            author: str = "",
            font: app_commands.Choice[str] | None = None,
            position: app_commands.Choice[str] | None = None,
            color: app_commands.Choice[str] | None = None,
            image: app_commands.Choice[str] | None = None,
        ) -> None:
            options = {"author": author}
            if font is not None:
                options["font"] = font.value
            if position is not None:
                options["text_position"] = position.value
            if color is not None:
                options["color_mode"] = color.value
            if image is not None:
                options["image_mode"] = image.value
            await self._execute(
                interaction,
                CapabilityName.QUOTE,
                source_attachment=attachment,
                text=quote,
                options=options,
            )

        @create_group.command(name="qr", description="Generate a QR code from text or a URL.")
        @app_commands.describe(value="Text or URL encoded in the QR code")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def create_qr(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            value: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.QR,
                text=value,
                options={"value": value},
            )

        tool_group = app_commands.Group(name="tool", description="Deterministic utilities.")

        random_modes = [
            app_commands.Choice(name="Coin flip", value="coin"),
            app_commands.Choice(name="Dice roll", value="dice"),
            app_commands.Choice(name="Random number", value="number"),
            app_commands.Choice(name="Choose from list", value="choose"),
            app_commands.Choice(name="Password", value="password"),
            app_commands.Choice(name="UUID", value="uuid"),
        ]
        text_modes = [
            app_commands.Choice(name="Count", value="count"),
            app_commands.Choice(name="Uppercase", value="upper"),
            app_commands.Choice(name="Lowercase", value="lower"),
            app_commands.Choice(name="Title case", value="title"),
            app_commands.Choice(name="Reverse", value="reverse"),
            app_commands.Choice(name="Trim whitespace", value="trim"),
            app_commands.Choice(name="Slug", value="slug"),
            app_commands.Choice(name="Sort lines", value="sort"),
            app_commands.Choice(name="Dedupe lines", value="dedupe"),
        ]
        encoding_modes = [
            app_commands.Choice(name="Base64 encode", value="base64_encode"),
            app_commands.Choice(name="Base64 decode", value="base64_decode"),
            app_commands.Choice(name="URL encode", value="url_encode"),
            app_commands.Choice(name="URL decode", value="url_decode"),
            app_commands.Choice(name="Hex encode", value="hex_encode"),
            app_commands.Choice(name="Hex decode", value="hex_decode"),
            app_commands.Choice(name="Hash", value="hash"),
        ]
        json_modes = [
            app_commands.Choice(name="Format", value="format"),
            app_commands.Choice(name="Minify", value="minify"),
            app_commands.Choice(name="Sort keys", value="sort"),
            app_commands.Choice(name="Validate", value="validate"),
        ]
        color_modes = [
            app_commands.Choice(name="Inspect", value="inspect"),
            app_commands.Choice(name="Complement", value="complement"),
            app_commands.Choice(name="Random", value="random"),
        ]
        timestamp_modes = [
            app_commands.Choice(name="Current time", value="now"),
            app_commands.Choice(name="Unix / Discord → date", value="unix"),
            app_commands.Choice(name="ISO date → timestamp", value="date"),
        ]
        image_operations = [
            app_commands.Choice(name="Resize", value="resize"),
            app_commands.Choice(name="Rotate", value="rotate"),
            app_commands.Choice(name="Mirror", value="mirror"),
            app_commands.Choice(name="Grayscale", value="grayscale"),
            app_commands.Choice(name="Blur", value="blur"),
            app_commands.Choice(name="Pixelate", value="pixelate"),
            app_commands.Choice(name="Deep fry", value="deepfry"),
        ]

        @tool_group.command(
            name="random",
            description="Flip, roll, choose, or generate safe values.",
        )
        @app_commands.describe(mode="Random operation", value="Examples: 2d20, 1-100, or a | b")
        @app_commands.choices(mode=random_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_random(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            value: str = "",
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.RANDOM,
                text=value,
                options={"mode": mode.value, "value": value},
            )

        @tool_group.command(name="text", description="Transform or measure text locally.")
        @app_commands.describe(mode="Text operation", text="Text to transform")
        @app_commands.choices(mode=text_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_text(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            text: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.TEXT,
                text=text,
                options={"mode": mode.value, "value": text},
            )

        @tool_group.command(name="encode", description="Encode, decode, or hash text locally.")
        @app_commands.describe(
            mode="Encoding operation",
            value="Text or encoded value",
            algorithm="Hash algorithm when mode is Hash",
        )
        @app_commands.choices(mode=encoding_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_encode(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            value: str,
            algorithm: str = "sha256",
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.ENCODE,
                text=value,
                options={"mode": mode.value, "value": value, "algorithm": algorithm},
            )

        @tool_group.command(name="json", description="Format, minify, sort, or validate JSON.")
        @app_commands.describe(mode="JSON operation", value="JSON text")
        @app_commands.choices(mode=json_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_json(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            value: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.JSON,
                text=value,
                options={"mode": mode.value, "value": value},
            )

        @tool_group.command(name="color", description="Inspect or complement a color.")
        @app_commands.describe(mode="Color operation", value="Hex, RGB, or common color name")
        @app_commands.choices(mode=color_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_color(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            value: str = "",
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.COLOR,
                text=value,
                options={"mode": mode.value, "value": value},
            )

        @tool_group.command(
            name="timestamp",
            description="Convert Unix, ISO, and Discord timestamps.",
        )
        @app_commands.describe(
            mode="Timestamp operation",
            value="Unix seconds, ISO date, or Discord timestamp markup",
            timezone="IANA timezone for display, such as Asia/Karachi",
        )
        @app_commands.choices(mode=timestamp_modes)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_timestamp(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            mode: app_commands.Choice[str],
            value: str = "",
            timezone: str = "UTC",
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.TIMESTAMP,
                text=value,
                options={"mode": mode.value, "value": value, "timezone": timezone},
            )

        @tool_group.command(name="image", description="Apply a fast local image effect.")
        @app_commands.describe(
            operation="Image operation",
            attachment="Image to process",
            width="Resize width, when using Resize",
            height="Resize height, when using Resize",
            degrees="Rotation degrees, when using Rotate",
        )
        @app_commands.choices(operation=image_operations)
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_image(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            operation: app_commands.Choice[str],
            attachment: discord.Attachment,
            width: int = 0,
            height: int = 0,
            degrees: int = 90,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.IMAGE_EDIT,
                source_attachment=attachment,
                options={
                    "operation": operation.value,
                    "width": str(width),
                    "height": str(height),
                    "degrees": str(degrees),
                },
            )

        @tool_group.command(
            name="fileinfo",
            description="Inspect one attachment without downloading it.",
        )
        @app_commands.describe(attachment="File to inspect")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_fileinfo(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.FILE_INFO,
                source_attachment=attachment,
            )

        @tool_group.command(name="calc", description="Safely calculate an expression.")
        @app_commands.describe(expression="Arithmetic expression")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_calc(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            expression: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.CALCULATE,
                text=expression,
                options={"expression": expression},
            )

        @tool_group.command(name="convert", description="Convert common units.")
        @app_commands.describe(expression="Example: 5 ft 11 in cm")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_convert(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            expression: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.CONVERT,
                text=expression,
                options={"expression": expression},
            )

        @tool_group.command(name="qr", description="Generate a QR code from text or a URL.")
        @app_commands.describe(value="Text or URL encoded in the QR code")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_qr(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            value: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.QR,
                text=value,
                options={"value": value},
            )

        @tool_group.command(name="emoji", description="Render a Unicode or custom Discord emoji.")
        @app_commands.describe(value="Emoji such as 😀 or <:party:123>")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_emoji(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            value: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.EMOJI,
                text=value,
                options={"value": value},
            )

        @tool_group.command(name="time", description="Convert a time between timezones.")
        @app_commands.describe(expression="Example: UK Islamabad, or 5pm UK Islamabad")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_time(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            expression: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.TIME,
                text=expression,
                options={"expression": expression},
            )

        @tool_group.command(name="weather", description="Check current weather for a location.")
        @app_commands.describe(location="City or place to check")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_weather(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            location: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.WEATHER,
                text=location,
                options={"location": location},
            )

        @tool_group.command(name="ocr", description="Extract text from an image attachment.")
        @app_commands.describe(attachment="Image to read")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_ocr(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.IMAGE_OCR,
                source_attachment=attachment,
            )

        @tool_group.command(name="transcribe", description="Transcribe an audio attachment.")
        @app_commands.describe(attachment="Audio file to transcribe")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_transcribe(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.TRANSCRIBE,
                source_attachment=attachment,
            )

        @tool_group.command(name="background", description="Remove an image background locally.")
        @app_commands.describe(attachment="Image to process")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_background(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.IMAGE_BACKGROUND_REMOVE,
                source_attachment=attachment,
            )

        @tool_group.command(name="file", description="Convert an attached file locally.")
        @app_commands.describe(
            attachment="File to convert",
            target="Output format: png, jpg, webp, gif, pdf, mp3, wav, or mp4",
        )
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def tool_file(  # pyright: ignore[reportUnusedFunction]
            interaction: discord.Interaction,
            attachment: discord.Attachment,
            target: str,
        ) -> None:
            await self._execute(
                interaction,
                CapabilityName.FILE_CONVERT,
                source_attachment=attachment,
                options={"target": target},
            )

        @app_commands.context_menu(name="Toolbox")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def toolbox_message(
            interaction: discord.Interaction,
            message: discord.Message,
        ) -> None:
            log_event(
                self._logger,
                "discord_message_toolbox_opened",
                actor_id=int(interaction.user.id),
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                target_message_id=int(message.id),
                target_attachment_count=len(message.attachments),
            )
            await self._renderer.render_message_toolbox(interaction, message)

        @app_commands.context_menu(name="Toolbox User")
        @app_commands.allowed_installs(guilds=True, users=True)
        @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
        async def toolbox_user(
            interaction: discord.Interaction,
            user: discord.User | discord.Member,
        ) -> None:
            log_event(
                self._logger,
                "discord_user_toolbox_opened",
                actor_id=int(interaction.user.id),
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                target_user_id=int(user.id),
            )
            await self._renderer.render_user_toolbox(interaction, user)

        self.tree.add_command(ping)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(help_command)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(toolbox_dashboard)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(find)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(search)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(ask)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(translate)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(what)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(research)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(factcheck)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(link)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(time_command)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(remind)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(reminders)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(cancel_reminder)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(saved)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(save)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(bookmark)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(bookmarks)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(send_saved)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(export_bookmarks)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(unsave)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(me_group)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(create_group)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(tool_group)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(toolbox_message)  # pyright: ignore[reportUnknownArgumentType]
        self.tree.add_command(toolbox_user)  # pyright: ignore[reportUnknownArgumentType]
        log_event(
            self._logger,
            "discord_commands_registered",
            commands=tuple(str(command.qualified_name) for command in self.tree.walk_commands()),
        )
        log_event(
            self._logger,
            "discord_command_sync_started",
            command_count=len(self.tree.get_commands()),
        )
        await self.tree.sync()
        log_event(self._logger, "discord_commands_synced")

    async def on_ready(self) -> None:
        """Record gateway readiness without logging tokens or message content."""

        if self._health is not None:
            self._health.set_component("Discord", HealthState.HEALTHY, "Gateway is ready")

        log_event(
            self._logger,
            "discord_ready",
            bot_user_id=self.user.id if self.user else None,
            bot_name=str(self.user) if self.user else None,
            guild_count=len(self.guilds),
        )

    async def on_disconnect(self) -> None:
        """Record a gateway disconnect for operational tuning."""

        if self._health is not None:
            self._health.set_component("Discord", HealthState.DEGRADED, "Gateway disconnected")

        log_event(self._logger, "discord_disconnected", level=logging.WARNING)

    async def on_resumed(self) -> None:
        """Record a successful gateway resume."""

        if self._health is not None:
            self._health.set_component("Discord", HealthState.HEALTHY, "Gateway session resumed")

        log_event(self._logger, "discord_resumed")

    async def on_connect(self) -> None:
        """Record the gateway connection boundary for lifecycle tuning."""

        if self._health is not None:
            self._health.set_component("Discord", HealthState.HEALTHY, "Gateway connected")

        log_event(self._logger, "discord_connected")

    async def on_close(self) -> None:
        """Record an intentional client close."""

        log_event(self._logger, "discord_closed")

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Capture command errors not handled by the normalized execution path."""

        command = interaction.command
        log_event(
            self._logger,
            "discord_app_command_failed",
            level=logging.ERROR,
            exc_info=(type(error), error, error.__traceback__),
            command_name=command.qualified_name if command is not None else None,
            actor_id=getattr(interaction.user, "id", None),
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
        )
        await self._send_safe_error(interaction)

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        """Record uncaught Discord event failures without serializing event payloads."""

        del args, kwargs
        log_event(
            self._logger,
            "discord_event_failed",
            level=logging.ERROR,
            exc_info=True,
            event_method=event_method,
        )

    async def _execute(
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
        started = time.perf_counter()
        try:
            request = self._mapper.from_interaction(
                interaction,
                capability,
                target_message=target_message,
                target_user=target_user,
                source_attachment=source_attachment,
                text=text,
                options=options,
                session_id=session_id,
            )
        except Exception:
            log_event(
                self._logger,
                "discord_interaction_mapping_failed",
                level=logging.ERROR,
                exc_info=True,
                capability=capability.value,
                actor_id=getattr(getattr(interaction, "user", None), "id", None),
                guild_id=getattr(interaction, "guild_id", None),
                channel_id=getattr(interaction, "channel_id", None),
            )
            await self._send_safe_error(interaction)
            return
        log_event(
            self._logger,
            "discord_interaction_started",
            request_id=str(request.request_id),
            capability=request.capability.value,
            actor_id=request.actor.user.user_id,
            guild_id=request.interaction.guild_id,
            channel_id=request.interaction.channel_id,
            surface=request.interaction.surface,
            public_allowed=request.interaction.public_allowed,
            has_target_message=request.target_message is not None,
            target_user_id=request.target_user.user_id if request.target_user else None,
            text_length=len(request.text or ""),
            option_names=tuple(sorted(request.options)),
            target_attachment_count=(
                len(request.target_message.attachments) if request.target_message else 0
            ),
            request_attachment_count=len(request.attachments),
        )

        try:
            should_defer = capability not in {CapabilityName.PING, CapabilityName.SHARE}
            if should_defer and not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
                log_event(
                    self._logger,
                    "discord_interaction_deferred",
                    request_id=str(request.request_id),
                    capability=request.capability.value,
                )
            result = await self._dispatcher.execute(request)
            await self._renderer.render(interaction, result)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            log_event(
                self._logger,
                "discord_interaction_failed",
                level=logging.ERROR,
                exc_info=True,
                request_id=str(request.request_id),
                capability=request.capability.value,
                actor_id=request.actor.user.user_id,
                guild_id=request.interaction.guild_id,
                channel_id=request.interaction.channel_id,
                duration_ms=duration_ms,
            )
            await self._send_safe_error(interaction)
            return

        log_event(
            self._logger,
            "discord_interaction_completed",
            request_id=str(request.request_id),
            capability=request.capability.value,
            actor_id=request.actor.user.user_id,
            guild_id=request.interaction.guild_id,
            channel_id=request.interaction.channel_id,
            result_type=type(result).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    @staticmethod
    async def _send_safe_error(interaction: discord.Interaction) -> None:
        """Send a private fallback without exposing internal exception details."""

        safe_error = ErrorResult(
            code="internal_error",
            message="Toolbox hit an internal error while handling that interaction.",
        )
        if interaction.response.is_done():
            await interaction.followup.send(
                safe_error.message,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.send_message(
                safe_error.message,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
