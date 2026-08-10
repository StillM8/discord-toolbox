from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from toolbox.app.dispatcher import Dispatcher
from toolbox.capabilities.ping import PingCapability
from toolbox.core.models import CapabilityName, ErrorResult, TextResult
from toolbox.interfaces.discord.mapper import DiscordMapper


@pytest.mark.asyncio
async def test_ping_round_trip_through_dispatcher() -> None:
    dispatcher = Dispatcher()
    dispatcher.register(CapabilityName.PING, PingCapability())

    request = DiscordMapper().from_interaction(
        SimpleNamespace(
            user=SimpleNamespace(id=42, display_name="Tester"),
            locale="en-US",
            guild_id=None,
            channel_id=7,
            context=SimpleNamespace(private_channel=True),
            _integration_owners={1: 42},
            app_permissions=SimpleNamespace(send_messages=False),
        ),
        CapabilityName.PING,
    )

    result = await dispatcher.execute(request)

    assert isinstance(result, TextResult)
    assert result.text == "Toolbox is online."
    assert request.actor.user.user_id == 42
    assert request.actor.installation_owner_id == 42
    assert request.interaction.surface == "private_channel"


@pytest.mark.asyncio
async def test_unknown_capability_returns_safe_error() -> None:
    dispatcher = Dispatcher()
    request = DiscordMapper().from_interaction(
        SimpleNamespace(
            user=SimpleNamespace(id=42, display_name="Tester"),
            locale=None,
            guild_id=1,
            channel_id=7,
            context=SimpleNamespace(name="guild"),
            authorizing_integration_owners={},
            app_permissions=SimpleNamespace(send_messages=True),
        ),
        CapabilityName.PING,
    )
    request = request.__class__(
        request_id=request.request_id,
        capability=cast(CapabilityName, "not_registered"),
        actor=request.actor,
        interaction=request.interaction,
    )

    result = await dispatcher.execute(request)

    assert isinstance(result, ErrorResult)
    assert result.code == "capability_not_found"


def test_message_target_is_normalized_without_discord_objects() -> None:
    message = SimpleNamespace(
        id=100,
        content="hello",
        author=SimpleNamespace(
            id=9,
            display_name="Author",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        ),
        channel=SimpleNamespace(id=8),
        guild=SimpleNamespace(id=7),
        reference=SimpleNamespace(message_id=99),
        attachments=(
            SimpleNamespace(
                id=1,
                url="https://cdn.example/image.png",
                filename="image.png",
                content_type="image/png",
                size=12,
            ),
        ),
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="Tester"),
        locale="en-US",
        guild_id=7,
        channel_id=8,
        context=SimpleNamespace(name="guild"),
        authorizing_integration_owners={},
        app_permissions=SimpleNamespace(send_messages=True),
    )

    request = DiscordMapper().from_interaction(
        interaction,
        CapabilityName.PING,
        target_message=message,
    )

    assert request.target_message is not None
    assert request.target_message.content == "hello"
    assert request.target_message.reply_to_message_id == 99
    assert request.target_message.attachments[0].filename == "image.png"
    assert request.target_message.author_avatar_url == "https://cdn.example/avatar.png"


def test_slash_attachment_is_normalized_without_retaining_discord_objects() -> None:
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="Tester"),
        locale=None,
        guild_id=None,
        channel_id=8,
        context=SimpleNamespace(name="dm"),
        authorizing_integration_owners={},
        app_permissions=SimpleNamespace(send_messages=False),
    )
    request = DiscordMapper().from_interaction(
        interaction,
        CapabilityName.TRANSCRIBE,
        source_attachment=SimpleNamespace(
            id=2,
            url="https://cdn.example/audio.wav",
            filename="audio.wav",
            content_type="audio/wav",
            size=64,
        ),
    )

    assert request.attachments[0].filename == "audio.wav"
    assert request.attachments[0].declared_content_type == "audio/wav"


def test_user_context_target_is_normalized_without_discord_objects() -> None:
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="Tester"),
        locale=None,
        guild_id=7,
        channel_id=8,
        context=SimpleNamespace(name="guild"),
        authorizing_integration_owners={},
        app_permissions=SimpleNamespace(send_messages=True),
    )
    request = DiscordMapper().from_interaction(
        interaction,
        CapabilityName.USER_INFO,
        target_user=SimpleNamespace(
            id=9,
            display_name="Target",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        ),
    )

    assert request.target_user is not None
    assert request.target_user.user_id == 9
    assert request.target_user.avatar_url == "https://cdn.example/avatar.png"


def test_user_installed_app_uses_use_external_apps_for_public_responses() -> None:
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="Tester"),
        locale=None,
        guild_id=7,
        channel_id=8,
        context=SimpleNamespace(name="guild"),
        authorizing_integration_owners={1: 42},
        app_permissions=SimpleNamespace(
            send_messages=False,
            use_external_apps=True,
        ),
    )

    request = DiscordMapper().from_interaction(interaction, CapabilityName.PING)

    assert request.interaction.public_allowed is True


def test_user_installed_app_leaves_public_visibility_to_discord() -> None:
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="Tester"),
        locale=None,
        guild_id=7,
        channel_id=8,
        context=SimpleNamespace(name="guild"),
        authorizing_integration_owners={1: 42},
        app_permissions=SimpleNamespace(
            send_messages=True,
            use_external_apps=False,
        ),
    )

    request = DiscordMapper().from_interaction(interaction, CapabilityName.PING)

    # Discord enforces Use External Apps for user-installed apps; it is not
    # reliably present in app_permissions for an app without a bot install.
    assert request.interaction.public_allowed is True


def test_guild_installed_app_uses_send_messages() -> None:
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42, display_name="Tester"),
        locale=None,
        guild_id=7,
        channel_id=8,
        context=SimpleNamespace(name="guild"),
        authorizing_integration_owners={0: 99},
        app_permissions=SimpleNamespace(send_messages=True, use_external_apps=False),
    )

    request = DiscordMapper().from_interaction(interaction, CapabilityName.PING)

    assert request.interaction.public_allowed is True
