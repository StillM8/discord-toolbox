from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import cast

import discord
import pytest
from discord import app_commands

from toolbox.app.dispatcher import Dispatcher
from toolbox.capabilities.calculate import CalculateCapability
from toolbox.core.models import CapabilityName, TextResult, ToolResult
from toolbox.interfaces.discord.bot import ToolboxBot
from toolbox.interfaces.discord.components import (
    ActionExecutor,
    MessageToolboxView,
    QuoteStyleView,
    UserToolboxView,
)
from toolbox.interfaces.discord.mapper import DiscordMapper
from toolbox.interfaces.discord.renderer import DiscordRenderer


@pytest.mark.asyncio
async def test_discord_surface_registers_thin_user_install_commands() -> None:
    bot = ToolboxBot(
        dispatcher=Dispatcher(),
        mapper=DiscordMapper(),
        renderer=DiscordRenderer(),
    )

    async def sync() -> None:
        return None

    bot.tree.sync = sync  # type: ignore[method-assign]
    await bot.setup_hook()

    registered = bot.tree.get_commands()
    names = {str(command.name) for command in registered}
    assert {
        "ping",
        "help",
        "toolbox",
        "find",
        "search",
        "ask",
        "translate",
        "what",
        "research",
        "factcheck",
        "link",
        "time",
        "remind",
        "reminders",
        "cancel-reminder",
        "saved",
        "save",
        "bookmark",
        "bookmarks",
        "send-saved",
        "export-bookmarks",
        "unsave",
        "me",
        "create",
        "tool",
        "Toolbox",
        "Toolbox User",
    }.issubset(names)
    tool = next(command for command in registered if str(command.name) == "tool")
    assert isinstance(tool, app_commands.Group)
    assert {command.name for command in tool.commands} == {
        "calc",
        "color",
        "convert",
        "encode",
        "fileinfo",
        "image",
        "json",
        "qr",
        "random",
        "text",
        "timestamp",
        "emoji",
        "time",
        "weather",
        "ocr",
        "transcribe",
        "background",
        "file",
    }
    create = next(command for command in registered if str(command.name) == "create")
    assert isinstance(create, app_commands.Group)
    assert {command.name for command in create.commands} == {
        "image",
        "edit",
        "meme",
        "caption",
        "quote",
        "qr",
    }
    me = next(command for command in registered if str(command.name) == "me")
    assert isinstance(me, app_commands.Group)
    assert {command.name for command in me.commands} == {
        "preferences",
        "accessibility",
        "status",
        "codex-login",
        "saved",
        "bookmarks",
        "export",
        "reminders",
        "context",
    }

    await bot.close()


@pytest.mark.asyncio
async def test_long_running_ingress_is_deferred_before_dispatch() -> None:
    dispatcher = Dispatcher()
    dispatcher.register(CapabilityName.CALCULATE, CalculateCapability())

    class Renderer:
        def __init__(self) -> None:
            self.result: ToolResult | None = None

        def bind_executor(self, executor: object) -> None:
            del executor

        async def render(self, interaction: object, result: ToolResult) -> None:
            del interaction
            self.result = result

    renderer = Renderer()
    bot = ToolboxBot(
        dispatcher=dispatcher,
        mapper=DiscordMapper(),
        renderer=cast(DiscordRenderer, renderer),
    )

    class Response:
        def __init__(self) -> None:
            self.done = False
            self.deferred = False

        def is_done(self) -> bool:
            return self.done

        async def defer(self, *, ephemeral: bool) -> None:
            assert ephemeral is True
            self.deferred = True
            self.done = True

        async def send_message(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self.done = True

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="Tester"),
        locale="en-US",
        guild_id=None,
        channel_id=7,
        context=SimpleNamespace(name="dm"),
        _integration_owners={1: 42},
        app_permissions=SimpleNamespace(send_messages=False),
        response=Response(),
        followup=SimpleNamespace(),
    )

    executor = cast(ActionExecutor, getattr(bot, "_execute"))
    await executor(cast(discord.Interaction, interaction), CapabilityName.CALCULATE, text="2 + 2")

    assert interaction.response.deferred is True
    assert renderer.result is not None
    assert renderer.result.__class__.__name__ == "TextResult"
    await bot.close()


def test_message_toolbox_exposes_quote_for_every_message() -> None:
    async def executor(*args: object, **kwargs: object) -> None:
        del args, kwargs

    message = SimpleNamespace(content="a message", attachments=())
    view = MessageToolboxView(
        cast(discord.Message, message),
        cast(ActionExecutor, executor),
    )

    assert any(getattr(item, "label", None) == "Quote" for item in view.children)


def test_quote_style_view_exposes_font_alignment_color_and_image_controls() -> None:
    async def executor(*args: object, **kwargs: object) -> None:
        del args, kwargs

    message = SimpleNamespace(content="A quote", attachments=())
    view = QuoteStyleView(
        cast(ActionExecutor, executor),
        message=cast(discord.Message, message),
    )

    placeholders = {
        getattr(item, "placeholder", None)
        for item in view.children
        if getattr(item, "placeholder", None) is not None
    }
    labels = {getattr(item, "label", None) for item in view.children}

    assert placeholders == {"Font", "Text position", "Photo color", "Photo placement"}
    assert "Generate" in labels
    assert "Cancel" in labels


def test_user_toolbox_exposes_avatar_quote() -> None:
    async def executor(*args: object, **kwargs: object) -> None:
        del args, kwargs

    user = SimpleNamespace(id=9, display_name="Author")
    view = UserToolboxView(
        cast(discord.User, user),
        cast(ActionExecutor, executor),
    )

    assert {getattr(item, "label", None) for item in view.children} == {
        "User info",
        "Quote avatar",
    }


@pytest.mark.asyncio
async def test_every_registered_discord_leaf_callback_maps_without_exception() -> None:
    """Exercise every current command callback without invoking real providers."""

    class Response:
        def __init__(self) -> None:
            self._done = False

        def is_done(self) -> bool:
            return self._done

        async def defer(self, *, ephemeral: bool) -> None:
            del ephemeral
            self._done = True

        async def send_message(self, **kwargs: object) -> None:
            del kwargs
            self._done = True

    class Followup:
        async def send(self, **kwargs: object) -> None:
            del kwargs

    class RecordingRenderer:
        def __init__(self) -> None:
            self.presentations: list[str] = []

        def bind_executor(self, executor: object) -> None:
            del executor

        async def render(self, interaction: object, result: ToolResult) -> None:
            del interaction, result

        async def render_dashboard(self, interaction: object) -> None:
            del interaction
            self.presentations.append("dashboard")

        async def render_message_toolbox(self, interaction: object, message: object) -> None:
            del interaction, message
            self.presentations.append("message")

        async def render_user_toolbox(self, interaction: object, user: object) -> None:
            del interaction, user
            self.presentations.append("user")

    class RecordingDispatcher:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request: object) -> TextResult:
            self.requests.append(request)
            return TextResult(title="smoke", text="ok")

    def interaction() -> SimpleNamespace:
        return SimpleNamespace(
            user=SimpleNamespace(id=42, display_name="Smoke", name="Smoke"),
            locale="en-US",
            guild_id=None,
            channel_id=7,
            context=SimpleNamespace(name="dm"),
            _integration_owners={1: 42},
            app_permissions=SimpleNamespace(send_messages=False),
            response=Response(),
            followup=Followup(),
            command=None,
        )

    attachment = SimpleNamespace(
        id=1,
        url="https://cdn.discordapp.com/a.png",
        filename="a.png",
        content_type="image/png",
        size=100,
    )

    def value(command: object, parameter: object) -> object:
        name = str(getattr(parameter, "name", ""))
        choices = getattr(parameter, "choices", ())
        if choices:
            return choices[0]
        if name == "attachment":
            return attachment
        if name in {"send_to_dm", "clear"}:
            return False
        if name in {"width", "height"}:
            return 720
        if name == "degrees":
            return 90
        if name in {"query", "question", "claim", "subject"}:
            return "cats"
        if name == "url":
            return "https://example.com"
        if name == "expression":
            command_name = str(getattr(command, "qualified_name", ""))
            return "2 + 2" if command_name == "tool calc" else "UK Islamabad"
        if name == "when":
            return "in 1 hour"
        if name == "note":
            return "smoke test"
        if name in {"text", "value"}:
            return "hello"
        if name == "language":
            return "English"
        if name == "source":
            return "auto"
        if name == "title":
            return "Smoke"
        if name == "tags":
            return "smoke"
        if name == "item_id":
            return "00000000-0000-0000-0000-000000000000"
        if name == "target":
            return "png"
        if name == "prompt":
            return "a blue square"
        if name == "top":
            return "TOP"
        if name == "bottom":
            return "BOTTOM"
        if name == "caption":
            return "CAPTION"
        if name == "quote":
            return "A quote"
        if name == "author":
            return "Author"
        if name == "location":
            return "Islamabad"
        if name == "algorithm":
            return "sha256"
        return "smoke"

    dispatcher = RecordingDispatcher()
    renderer = RecordingRenderer()
    bot = ToolboxBot(
        dispatcher=cast(Dispatcher, dispatcher),
        mapper=DiscordMapper(),
        renderer=cast(DiscordRenderer, renderer),
    )

    async def sync() -> None:
        return None

    bot.tree.sync = sync  # type: ignore[method-assign]
    await bot.setup_hook()

    failures: list[str] = []
    slash_leaf_count = 0
    for command in bot.tree.walk_commands():
        if isinstance(command, app_commands.Group):
            continue
        slash_leaf_count += 1
        try:
            arguments = [value(command, parameter) for parameter in command.parameters]
            callback = cast(Callable[..., Awaitable[None]], command.callback)
            await callback(
                cast(discord.Interaction, interaction()),
                *arguments,
            )
        except Exception as error:  # pragma: no cover - assertion reports the command
            failures.append(f"{command.qualified_name}: {type(error).__name__}: {error}")

    context_menu_count = 0
    for command in bot.tree.get_commands():
        if not isinstance(command, app_commands.ContextMenu):
            continue
        context_menu_count += 1
        try:
            target: object
            if command.name == "Toolbox":
                target = SimpleNamespace(
                    id=8,
                    content="hello",
                    attachments=(),
                    author=SimpleNamespace(id=9, display_name="Author"),
                    channel=None,
                    guild=None,
                    reference=None,
                )
            else:
                target = SimpleNamespace(id=9, display_name="Author")
            callback = cast(Callable[..., Awaitable[None]], command.callback)
            await callback(
                cast(discord.Interaction, interaction()),
                target,
            )
        except Exception as error:  # pragma: no cover - assertion reports the command
            failures.append(f"{command.name}: {type(error).__name__}: {error}")

    assert slash_leaf_count == 55
    assert context_menu_count == 2
    assert len(dispatcher.requests) == 54
    assert renderer.presentations == ["dashboard", "message", "user"]
    assert failures == []
    await bot.close()
