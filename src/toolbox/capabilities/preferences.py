"""Owner-scoped preferences without leaking persistence into Discord."""

from __future__ import annotations

import re
from dataclasses import replace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from toolbox.core.contracts import PreferencesRepository
from toolbox.core.models import (
    AIProfile,
    ErrorResult,
    TextResult,
    ToolRequest,
    ToolResult,
    UserPreferences,
    Visibility,
)


class PreferencesCapability:
    """Read or update a small, validated set of personal preferences."""

    _currency = re.compile(r"^[A-Za-z]{3}$")
    _settings = {
        "timezone",
        "language",
        "currency",
        "visibility",
        "profile",
        "plain_text",
        "high_contrast",
        "reduce_motion",
        "verbose",
    }
    _aliases = {
        "plain": "plain_text",
        "screen_reader": "plain_text",
        "contrast": "high_contrast",
        "motion": "reduce_motion",
        "descriptions": "verbose",
    }

    def __init__(self, repository: PreferencesRepository) -> None:
        self._repository = repository

    async def execute(self, request: ToolRequest) -> ToolResult:
        owner_id = request.actor.user.user_id
        preferences = await self._repository.get(owner_id)
        setting = request.options.get("setting", "").strip().lower()
        value = (request.options.get("value") or request.text or "").strip()
        if not setting:
            return TextResult(
                title="Your Toolbox preferences",
                text=(
                    f"Timezone: `{preferences.timezone}`\n"
                    f"Language: `{preferences.language}`\n"
                    f"Currency: `{preferences.currency}`\n"
                    f"Visibility: `{preferences.visibility.value}`\n"
                    f"AI profile: `{preferences.default_profile.value}`\n"
                    f"Plain text: `{_on_off(preferences.accessibility_plain_text)}`\n"
                    f"High contrast: `{_on_off(preferences.accessibility_high_contrast)}`\n"
                    f"Reduce motion: `{_on_off(preferences.accessibility_reduce_motion)}`\n"
                    f"Verbose descriptions: `{_on_off(preferences.accessibility_verbose)}`"
                ),
            )
        setting = self._aliases.get(setting, setting)
        if setting not in self._settings or not value:
            return ErrorResult(
                code="invalid_request",
                message=(
                    "Choose timezone, language, currency, visibility, profile, plain_text, "
                    "high_contrast, reduce_motion, or verbose with a value."
                ),
            )
        try:
            updated = self._update(preferences, setting, value)
        except ValueError:
            return ErrorResult(
                code="invalid_request",
                message="That preference value is not valid.",
            )
        await self._repository.save(updated)
        return TextResult(title="Preference updated", text=f"`{setting}` is now `{value}`.")

    @staticmethod
    def _update(preferences: UserPreferences, setting: str, value: str) -> UserPreferences:
        if setting == "timezone":
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as error:
                raise ValueError from error
            return replace(preferences, timezone=value)
        if setting == "language":
            if len(value) > 50:
                raise ValueError
            return replace(preferences, language=value)
        if setting == "currency":
            if not PreferencesCapability._currency.fullmatch(value):
                raise ValueError
            return replace(preferences, currency=value.upper())
        if setting == "visibility":
            return replace(preferences, visibility=Visibility(value.lower()))
        if setting == "profile":
            return replace(preferences, default_profile=AIProfile(value.lower()))
        if setting in {
            "plain_text",
            "high_contrast",
            "reduce_motion",
            "verbose",
        }:
            enabled = _parse_bool(value)
            fields = {
                "plain_text": "accessibility_plain_text",
                "high_contrast": "accessibility_high_contrast",
                "reduce_motion": "accessibility_reduce_motion",
                "verbose": "accessibility_verbose",
            }
            return replace(preferences, **{fields[setting]: enabled})
        raise ValueError


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"on", "true", "yes", "1", "enabled"}:
        return True
    if normalized in {"off", "false", "no", "0", "disabled"}:
        return False
    raise ValueError


def _on_off(value: bool) -> str:
    return "on" if value else "off"
