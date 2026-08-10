from __future__ import annotations

from uuid import uuid4

import pytest

from toolbox.capabilities.preferences import PreferencesCapability
from toolbox.core.models import (
    ActorContext,
    AIProfile,
    CapabilityName,
    InteractionContext,
    ToolRequest,
    UserContext,
    UserPreferences,
)


class Preferences:
    def __init__(self) -> None:
        self.value = UserPreferences(owner_id=42)

    async def get(self, owner_id: int) -> UserPreferences:
        assert owner_id == 42
        return self.value

    async def save(self, preferences: UserPreferences) -> None:
        self.value = preferences


def request(**options: str) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.PREFERENCES,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        options=options,
    )


@pytest.mark.asyncio
async def test_preferences_are_owner_scoped_and_typed() -> None:
    repository = Preferences()
    capability = PreferencesCapability(repository)

    result = await capability.execute(request(setting="timezone", value="Asia/Karachi"))
    assert result.text.startswith("`timezone`")  # type: ignore[attr-defined]
    assert repository.value.timezone == "Asia/Karachi"

    result = await capability.execute(request(setting="profile", value="research"))
    assert result.text.startswith("`profile`")  # type: ignore[attr-defined]
    assert repository.value.default_profile is AIProfile.RESEARCH


@pytest.mark.asyncio
async def test_preferences_reject_invalid_values() -> None:
    repository = Preferences()
    result = await PreferencesCapability(repository).execute(
        request(setting="timezone", value="Not/AZone")
    )

    assert result.code == "invalid_request"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_accessibility_preferences_are_persisted_and_reported() -> None:
    repository = Preferences()
    capability = PreferencesCapability(repository)

    await capability.execute(request(setting="plain", value="on"))
    await capability.execute(request(setting="contrast", value="yes"))
    await capability.execute(request(setting="motion", value="off"))
    await capability.execute(request(setting="descriptions", value="enabled"))

    assert repository.value.accessibility_plain_text is True
    assert repository.value.accessibility_high_contrast is True
    assert repository.value.accessibility_reduce_motion is False
    assert repository.value.accessibility_verbose is True

    result = await capability.execute(request())
    assert "Plain text: `on`" in result.text  # type: ignore[attr-defined]
    assert "High contrast: `on`" in result.text  # type: ignore[attr-defined]
    assert "Reduce motion: `off`" in result.text  # type: ignore[attr-defined]
    assert "Verbose descriptions: `on`" in result.text  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_accessibility_preferences_reject_non_boolean_values() -> None:
    result = await PreferencesCapability(Preferences()).execute(
        request(setting="plain_text", value="maybe")
    )

    assert result.code == "invalid_request"  # type: ignore[attr-defined]
