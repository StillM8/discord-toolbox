from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import discord
import pytest

from toolbox.core.models import CapabilityName, HelpResult, HelpSection
from toolbox.interfaces.discord.components import ActionExecutor
from toolbox.interfaces.discord.dashboard import (
    DashboardActionSelect,
    DashboardCategorySelect,
    HelpCloseButton,
    HelpPageButton,
    HelpView,
    ToolboxDashboardView,
)


async def noop_executor(*args: object, **kwargs: object) -> None:
    del args, kwargs


class EditResponse:
    def __init__(self) -> None:
        self.edited: dict[str, object] | None = None

    async def edit_message(self, **kwargs: object) -> None:
        self.edited = kwargs


class EditInteraction:
    def __init__(self) -> None:
        self.response = EditResponse()


def _action_select(view: ToolboxDashboardView) -> DashboardActionSelect:
    action_select = next(
        child for child in view.children if isinstance(child, DashboardActionSelect)
    )
    return action_select


def test_home_dashboard_is_compact_and_future_action_friendly() -> None:
    view = ToolboxDashboardView(cast(ActionExecutor, noop_executor))

    assert view.category == "home"
    assert any(isinstance(child, DashboardCategorySelect) for child in view.children)
    assert len(view.children) == 4
    assert {option.label for option in _action_select(view).options} == {
        "Ask anything",
        "Search the web",
        "Create an image",
        "Calculate",
        "Saved items",
    }


def test_dashboard_keeps_high_contrast_across_navigation() -> None:
    view = ToolboxDashboardView(
        cast(ActionExecutor, noop_executor),
        high_contrast=True,
    )

    assert view.embed().colour == discord.Colour.from_rgb(255, 255, 255)


@pytest.mark.asyncio
async def test_dashboard_sections_replace_actions_without_dispatching() -> None:
    view = ToolboxDashboardView(cast(ActionExecutor, noop_executor))
    interaction = EditInteraction()

    await view.select_category(cast(discord.Interaction, interaction), "search")

    assert view.category == "search"
    assert {option.label for option in _action_select(view).options} == {
        "Web",
        "Images",
        "News",
        "Video",
        "GIFs",
    }
    assert interaction.response.edited is not None
    assert interaction.response.edited["view"] is view


@pytest.mark.asyncio
async def test_tools_dashboard_exposes_the_local_utility_pack() -> None:
    view = ToolboxDashboardView(cast(ActionExecutor, noop_executor))
    await view.select_category(cast(discord.Interaction, EditInteraction()), "tools")

    labels = {option.label for option in _action_select(view).options}
    assert {
        "Flip a coin",
        "Count text",
        "Hash text",
        "Format JSON",
        "Inspect color",
        "Timestamp now",
        "Calculate",
        "Convert",
    }.issubset(labels)


def test_selected_message_dashboard_keeps_target_actions_in_one_menu() -> None:
    message = SimpleNamespace(content="A selected message", attachments=())
    view = ToolboxDashboardView(
        cast(ActionExecutor, noop_executor),
        target_message=cast(discord.Message, message),
    )

    assert view.category == "selected"
    assert {option.label for option in _action_select(view).options} >= {
        "Ask about it",
        "What is this?",
        "Search it",
        "Translate",
        "Fact check",
        "Save",
    }
    assert "A selected message" in (view.embed().description or "") or any(
        field.name == "Selected message" for field in view.embed().fields
    )


def test_help_view_starts_with_previous_disabled_and_next_enabled() -> None:
    view = HelpView(
        HelpResult(
            sections=(
                HelpSection("General", ("`/help`",)),
                HelpSection("Tools", ("`/tool calc`",)),
            )
        )
    )

    buttons = {child.label: child for child in view.children if isinstance(child, HelpPageButton)}
    assert buttons["Previous"].disabled is True
    assert buttons["Next"].disabled is False
    fields = view.embed().to_dict().get("fields", [])
    assert fields and "General" in fields[0]["name"]


def test_help_view_uses_discord_valid_close_emoji() -> None:
    view = HelpView(HelpResult(sections=(HelpSection("General", ("`/help`",)),)))

    close = next(child for child in view.children if isinstance(child, HelpCloseButton))

    assert close.emoji is not None
    assert close.emoji.name == "❌"


def test_dashboard_actions_use_application_capability_names() -> None:
    view = ToolboxDashboardView(cast(ActionExecutor, noop_executor))
    keys = {option.value for option in _action_select(view).options}

    assert "ask" in keys
    assert "search" in keys
    assert all(isinstance(option.value, str) for option in _action_select(view).options)
    assert CapabilityName.ASK.value == "ask"
