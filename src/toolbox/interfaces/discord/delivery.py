"""Discord delivery adapter for durable reminder notifications."""

from __future__ import annotations

import discord

from toolbox.core.models import Reminder, SavedItem

from .renderer import DiscordRenderer


class DiscordReminderDelivery:
    """Deliver one already-authorized reminder as a DM."""

    def __init__(self, client: discord.Client, renderer: DiscordRenderer) -> None:
        self._client = client
        self._renderer = renderer

    async def deliver(self, reminder: Reminder) -> None:
        user = self._client.get_user(reminder.owner_id)
        if user is None:
            user = await self._client.fetch_user(reminder.owner_id)
        await self._renderer.render_reminder(user, reminder)


class DiscordSavedItemDelivery:
    """Deliver one owner-scoped saved item through Discord DMs."""

    def __init__(self, client: discord.Client, renderer: DiscordRenderer) -> None:
        self._client = client
        self._renderer = renderer

    async def deliver(self, item: SavedItem) -> None:
        user = self._client.get_user(item.owner_id)
        if user is None:
            user = await self._client.fetch_user(item.owner_id)
        await self._renderer.render_saved_item(user, item)
