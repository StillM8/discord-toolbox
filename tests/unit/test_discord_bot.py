from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import discord
import pytest
from discord import app_commands

from toolbox.app.dispatcher import Dispatcher
from toolbox.capabilities.calculate import CalculateCapability
from toolbox.core.models import CapabilityName, ToolResult
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
        "convert",
        "qr",
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

        async def send_message(self, **kwargs: object) -> None:
            del kwargs
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
