from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import discord
import pytest

from toolbox.core.actions import send_dm_action
from toolbox.core.models import (
    ActionKind,
    CapabilityName,
    HelpResult,
    HelpSection,
    InteractionSession,
    Reminder,
    ReminderStatus,
    SearchKind,
    SearchResultItem,
    SearchResults,
    TextResult,
    ToolAction,
    UserPreferences,
)
from toolbox.interfaces.discord.components import (
    ActionExecutor,
    QuoteStyleView,
    SessionActionView,
)
from toolbox.interfaces.discord.dashboard import (
    DashboardActionSelect,
    HelpView,
    ToolboxDashboardView,
)
from toolbox.interfaces.discord.mapper import DiscordMapper
from toolbox.interfaces.discord.renderer import DiscordRenderer


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class Sessions:
    def __init__(self) -> None:
        self.created: InteractionSession | None = None

    async def create(self, session: InteractionSession) -> None:
        self.created = session

    async def get(self, owner_id: int, session_id: UUID) -> InteractionSession | None:
        return self.created

    async def delete(self, owner_id: int, session_id: UUID) -> None:
        self.created = None


class Executor:
    def __init__(self) -> None:
        self.calls: list[tuple[CapabilityName, UUID | None]] = []
        self.targets: list[object | None] = []

    async def __call__(
        self,
        interaction: discord.Interaction,
        capability: CapabilityName,
        *,
        target_message: discord.Message | None = None,
        text: str | None = None,
        options: Mapping[str, str] | None = None,
        session_id: UUID | None = None,
    ) -> None:
        del interaction, text, options
        self.calls.append((capability, session_id))
        self.targets.append(target_message)


class Response:
    def __init__(self) -> None:
        self.sent: dict[str, object] | None = None

    def is_done(self) -> bool:
        return False

    async def send_message(self, **kwargs: object) -> None:
        self.sent = kwargs


class Followup:
    async def send(self, **kwargs: object) -> None:
        del kwargs


class FakeInteraction:
    def __init__(self) -> None:
        self.user = SimpleNamespace(id=42)
        self.response = Response()
        self.followup = Followup()


def interaction() -> FakeInteraction:
    return FakeInteraction()


class Preferences:
    def __init__(self, value: UserPreferences) -> None:
        self.value = value

    async def get(self, owner_id: int) -> UserPreferences:
        assert owner_id == 42
        return self.value

    async def save(self, preferences: UserPreferences) -> None:
        self.value = preferences


@pytest.mark.asyncio
async def test_private_result_creates_opaque_share_session() -> None:
    sessions = Sessions()
    executor = Executor()
    renderer = DiscordRenderer(sessions=sessions, clock=FixedClock())
    renderer.bind_executor(cast(ActionExecutor, executor))
    source = interaction()

    await renderer.render(
        source,
        TextResult(
            title="Answer",
            text="private answer",
            input_text="why is this useful?",
            actions=(ToolAction(kind=ActionKind.SHARE, label="Share"),),
        ),
    )

    assert sessions.created is not None
    assert sessions.created.owner_id == 42
    assert sessions.created.action is ActionKind.SHARE
    assert sessions.created.payload["text"] == "private answer"
    assert sessions.created.payload["input_text"] == "why is this useful?"
    assert source.response.sent is not None
    assert source.response.sent["ephemeral"] is True
    embed = source.response.sent["embed"]
    assert isinstance(embed, discord.Embed)
    embed_payload = embed.to_dict()
    fields = embed_payload.get("fields", [])
    assert fields[0]["name"] == "Request"
    assert fields[0]["value"] == "why is this useful?"
    view = source.response.sent["view"]
    assert isinstance(view, SessionActionView)
    button = view.children[0]
    assert isinstance(button, discord.ui.Button)
    assert button.custom_id is not None
    assert button.custom_id.startswith("tbx:v1:act:")
    assert "private answer" not in button.custom_id


@pytest.mark.asyncio
async def test_plain_text_accessibility_avoids_embed_and_keeps_request_visible() -> None:
    source = interaction()
    renderer = DiscordRenderer(
        preferences=Preferences(UserPreferences(owner_id=42, accessibility_plain_text=True))
    )

    await renderer.render(
        source,
        TextResult(
            title="Translation",
            text="Hello there",
            input_text="Welay khu jagara wi",
        ),
    )

    assert source.response.sent is not None
    assert source.response.sent.get("embed") is None
    assert "Translation" in str(source.response.sent["content"])
    assert "Welay khu jagara wi" in str(source.response.sent["content"])


@pytest.mark.asyncio
async def test_high_contrast_and_reduced_motion_change_search_presentation() -> None:
    source = interaction()
    renderer = DiscordRenderer(
        preferences=Preferences(
            UserPreferences(
                owner_id=42,
                accessibility_high_contrast=True,
                accessibility_reduce_motion=True,
                accessibility_verbose=True,
            )
        )
    )

    await renderer.render(
        source,
        SearchResults(
            query="shoebill",
            kind=SearchKind.IMAGES,
            items=(
                SearchResultItem(
                    title="Shoebill image",
                    url="https://example.com/shoebill",
                    thumbnail_url="https://example.com/shoebill.jpg",
                ),
            ),
        ),
    )

    assert source.response.sent is not None
    embed = source.response.sent.get("embed")
    assert isinstance(embed, discord.Embed)
    assert embed.colour == discord.Colour.from_rgb(255, 255, 255)
    assert embed.image.url is None
    assert "URL: https://example.com/shoebill" in (embed.description or "")


@pytest.mark.asyncio
async def test_private_saved_result_creates_owner_bound_dm_session() -> None:
    sessions = Sessions()
    executor = Executor()
    renderer = DiscordRenderer(sessions=sessions, clock=FixedClock())
    renderer.bind_executor(cast(ActionExecutor, executor))
    source = interaction()
    item_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    await renderer.render(
        source,
        TextResult(
            title="Saved",
            text="Saved privately.",
            actions=(send_dm_action(item_id),),
        ),
    )

    assert sessions.created is not None
    assert sessions.created.action is ActionKind.SEND_DM
    assert sessions.created.payload == {"item_id": str(item_id)}
    view = source.response.sent["view"] if source.response.sent is not None else None
    assert isinstance(view, SessionActionView)
    assert getattr(view.children[0], "label", None) == "Send to DM"


@pytest.mark.asyncio
async def test_message_toolbox_is_a_private_ui_adapter() -> None:
    renderer = DiscordRenderer()
    executor = Executor()
    renderer.bind_executor(cast(ActionExecutor, executor))
    source = interaction()
    message = cast(discord.Message, SimpleNamespace(id=7, content="selected"))

    await renderer.render_message_toolbox(source, message)

    assert source.response.sent is not None
    assert source.response.sent["ephemeral"] is True
    view = source.response.sent["view"]
    assert isinstance(view, ToolboxDashboardView)
    assert len(view.children) == 4
    action_select = next(
        child
        for child in view.children
        if getattr(child, "placeholder", None) == "Choose an action"
    )
    assert isinstance(action_select, DashboardActionSelect)
    labels: set[str] = {option.label for option in action_select.options}
    assert {"Ask about it", "Search it", "Translate", "Save"}.issubset(labels)


@pytest.mark.asyncio
async def test_quote_style_panel_defers_and_shows_only_source_image_above_controls() -> None:
    class DeferredResponse:
        def __init__(self) -> None:
            self.done = False
            self.deferred = False

        def is_done(self) -> bool:
            return self.done

        async def defer(self, *, ephemeral: bool) -> None:
            assert ephemeral is True
            self.deferred = True
            self.done = True

    class CapturingFollowup:
        def __init__(self) -> None:
            self.sent: dict[str, object] | None = None

        async def send(self, **kwargs: object) -> None:
            self.sent = kwargs

    response = DeferredResponse()
    followup = CapturingFollowup()
    source = SimpleNamespace(response=response, followup=followup)
    renderer = DiscordRenderer()
    renderer.bind_executor(cast(ActionExecutor, Executor()))
    message = SimpleNamespace(
        attachments=(
            SimpleNamespace(
                content_type="image/png",
                filename="source.png",
                url="https://cdn.example/source.png",
            ),
        ),
        author=SimpleNamespace(display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png")),
    )

    await renderer.render_quote_style(source, message=cast(discord.Message, message))

    assert response.deferred is True
    assert followup.sent is not None
    embed = followup.sent["embed"]
    assert isinstance(embed, discord.Embed)
    assert embed.description is None
    image = embed.to_dict().get("image")
    assert isinstance(image, dict)
    assert image.get("url") == "https://cdn.example/source.png"
    assert isinstance(followup.sent["view"], QuoteStyleView)


@pytest.mark.asyncio
async def test_quote_style_panel_renders_and_refreshes_a_real_preview() -> None:
    class Preview:
        def __init__(self) -> None:
            self.request = None

        async def render_preview(self, request: object) -> bytes:
            self.request = request
            return b"quote-png"

    class RefreshResponse:
        def __init__(self) -> None:
            self.edited: dict[str, object] | None = None

        def is_done(self) -> bool:
            return False

        async def defer(self) -> None:
            return None

    class RefreshInteraction:
        def __init__(self) -> None:
            self.user = SimpleNamespace(id=42)
            self.guild_id = 3
            self.channel_id = 2
            self.response = RefreshResponse()

        async def edit_original_response(self, **kwargs: object) -> None:
            self.response.edited = kwargs

    class CapturingFollowup:
        def __init__(self) -> None:
            self.sent: dict[str, object] | None = None

        async def send(self, **kwargs: object) -> None:
            self.sent = kwargs

    preview = Preview()

    class InitialResponse:
        def __init__(self) -> None:
            self.done = False

        def is_done(self) -> bool:
            return self.done

        async def defer(self, *, ephemeral: bool) -> None:
            assert ephemeral is True
            self.done = True

    initial_response = InitialResponse()
    source = SimpleNamespace(
        user=SimpleNamespace(id=42),
        guild_id=3,
        channel_id=2,
        response=initial_response,
        followup=CapturingFollowup(),
    )
    message = SimpleNamespace(
        id=7,
        content="A live preview",
        reference=None,
        channel=SimpleNamespace(id=2),
        guild=SimpleNamespace(id=3),
        attachments=(),
        author=SimpleNamespace(
            id=99,
            display_name="Author",
            display_avatar=SimpleNamespace(url="https://cdn.example/avatar.png"),
        ),
    )
    renderer = DiscordRenderer(quote_preview=preview, mapper=DiscordMapper())
    renderer.bind_executor(cast(ActionExecutor, Executor()))

    await renderer.render_quote_style(source, message=cast(discord.Message, message))

    assert preview.request is not None
    assert source.followup.sent is not None
    assert "file" in source.followup.sent
    view = source.followup.sent["view"]
    assert isinstance(view, QuoteStyleView)

    component = RefreshInteraction()
    await renderer.refresh_quote_style(
        component,  # type: ignore[arg-type]
        message=cast(discord.Message, message),
        options={
            "font": "serif",
            "text_position": "right",
            "color_mode": "color",
            "image_mode": "left",
        },
        view=view,
    )

    assert component.response.edited is not None
    assert component.response.edited["attachments"]


@pytest.mark.asyncio
async def test_message_toolbox_search_forwards_the_selected_message() -> None:
    renderer = DiscordRenderer()
    executor = Executor()
    renderer.bind_executor(cast(ActionExecutor, executor))
    source = interaction()
    message = cast(
        discord.Message,
        SimpleNamespace(id=7, content="why do cats chirp", attachments=()),
    )

    await renderer.render_message_toolbox(source, message)
    view = source.response.sent["view"] if source.response.sent is not None else None
    assert isinstance(view, ToolboxDashboardView)

    await view.activate_action(cast(discord.Interaction, source), "search")

    assert executor.calls == [(CapabilityName.SEARCH_WEB, None)]
    assert executor.targets == [message]


@pytest.mark.asyncio
async def test_search_renderer_keeps_pagination_action_opaque() -> None:
    sessions = Sessions()
    executor = Executor()
    renderer = DiscordRenderer(sessions=sessions, clock=FixedClock())
    renderer.bind_executor(cast(ActionExecutor, executor))
    source = interaction()
    next_session = UUID("11111111-1111-1111-1111-111111111111")
    expand_session = UUID("22222222-2222-2222-2222-222222222222")
    previous_session = UUID("33333333-3333-3333-3333-333333333333")

    await renderer.render(
        source,
        SearchResults(
            query="cats",
            items=(SearchResultItem(title="Cats", url="https://example.com"),),
            kind=SearchKind.WEB,
            actions=(
                ToolAction(kind=ActionKind.SHARE, label="Share"),
                ToolAction(
                    kind=ActionKind.EXPAND,
                    label="Expand",
                    session_id=expand_session,
                ),
                ToolAction(
                    kind=ActionKind.PREVIOUS_PAGE,
                    label="Back",
                    session_id=previous_session,
                ),
                ToolAction(kind=ActionKind.NEXT_PAGE, label="Next", session_id=next_session),
            ),
        ),
    )

    assert source.response.sent is not None
    view = source.response.sent["view"]
    assert isinstance(view, discord.ui.View)
    assert len(view.children) == 4
    assert [getattr(child, "label", None) for child in view.children] == [
        "Share",
        "Expand",
        "Back",
        "Next",
    ]
    assert all("cats" not in (getattr(button, "custom_id", "") or "") for button in view.children)


@pytest.mark.asyncio
async def test_help_renderer_uses_a_navigable_section_view() -> None:
    renderer = DiscordRenderer()
    renderer.bind_executor(cast(ActionExecutor, Executor()))
    source = interaction()

    await renderer.render(
        source,
        HelpResult(
            sections=(
                HelpSection("Search", ("`/search <query>`", "`/find <query>`")),
                HelpSection("Tools", ("`/tool calc <expression>`",)),
            )
        ),
    )

    assert source.response.sent is not None
    assert source.response.sent["ephemeral"] is True
    embed = source.response.sent["embed"]
    assert isinstance(embed, discord.Embed)
    payload = embed.to_dict()
    fields = payload.get("fields", [])
    assert [field["name"] for field in fields] == ["Search"]
    assert "`/search <query>`" in fields[0]["value"]
    view = source.response.sent["view"]
    assert isinstance(view, HelpView)
    assert len(view.children) == 4


@pytest.mark.asyncio
async def test_renderer_owns_reminder_message_presentation() -> None:
    class User:
        def __init__(self) -> None:
            self.sent: dict[str, object] | None = None

        async def send(self, **kwargs: object) -> None:
            self.sent = kwargs

    user = User()
    reminder = Reminder(
        reminder_id=UUID("11111111-1111-1111-1111-111111111111"),
        owner_id=42,
        due_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        payload="@everyone drink water",
        status=ReminderStatus.PENDING,
    )

    await DiscordRenderer().render_reminder(user, reminder)

    assert user.sent is not None
    assert "@everyone" not in str(user.sent["content"])
