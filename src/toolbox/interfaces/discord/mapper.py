"""Discord-to-core request mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID, uuid4

from toolbox.core.models import (
    ActorContext,
    AttachmentRef,
    CapabilityName,
    InteractionContext,
    MessageContext,
    ToolRequest,
    UserContext,
    Visibility,
)


class DiscordMapper:
    """Convert Discord interaction data into neutral application objects."""

    def from_interaction(
        self,
        interaction: Any,
        capability: CapabilityName,
        *,
        target_message: Any | None = None,
        target_user: Any | None = None,
        source_attachment: Any | None = None,
        text: str | None = None,
        options: Mapping[str, str] | None = None,
        session_id: UUID | None = None,
    ) -> ToolRequest:
        """Map an interaction and optional resolved message target."""

        user = interaction.user
        owners = cast(
            Mapping[object, object],
            getattr(
                interaction,
                "authorizing_integration_owners",
                getattr(interaction, "_integration_owners", {}),
            ),
        )
        installation_owner_id = self._user_install_owner(owners)

        context = getattr(interaction, "context", None)
        surface = self._surface_name(context)
        locale = getattr(interaction, "locale", None)

        return ToolRequest(
            request_id=uuid4(),
            capability=capability,
            actor=ActorContext(
                user=UserContext(
                    user_id=int(user.id),
                    display_name=getattr(user, "display_name", getattr(user, "name", "unknown")),
                    locale=str(locale) if locale is not None else None,
                ),
                installation_owner_id=installation_owner_id,
            ),
            interaction=InteractionContext(
                guild_id=getattr(interaction, "guild_id", None),
                channel_id=getattr(interaction, "channel_id", None),
                surface=surface,
                public_allowed=self._public_allowed(interaction, owners),
            ),
            text=text,
            target_message=self._message_context(target_message) if target_message else None,
            target_user=self._user_context(target_user) if target_user else None,
            attachments=(self._attachment_ref(source_attachment),)
            if source_attachment is not None
            else (),
            options=dict(options or {}),
            session_id=session_id,
            requested_visibility=Visibility.PRIVATE,
        )

    @staticmethod
    def _user_install_owner(owners: Mapping[object, object]) -> int | None:
        """Read Discord's user-install owner ID without leaking transport data inward."""

        raw_owner = owners.get("1")
        if raw_owner is None:
            raw_owner = owners.get(1)
        if raw_owner is None:
            return None
        if isinstance(raw_owner, int):
            return raw_owner
        if isinstance(raw_owner, str):
            try:
                return int(raw_owner)
            except ValueError:
                return None
        return None

    @staticmethod
    def _surface_name(context: Any) -> str:
        """Normalize discord.py's command-context flags for the core model."""

        explicit_name = getattr(context, "name", None)
        if explicit_name:
            return str(explicit_name)
        if getattr(context, "guild", False):
            return "guild"
        if getattr(context, "dm_channel", False):
            return "dm"
        if getattr(context, "private_channel", False):
            return "private_channel"
        return "unknown"

    @staticmethod
    def _public_allowed(interaction: Any, owners: Mapping[object, object]) -> bool:
        """Read the correct public-response capability for this installation.

        A user-installed app is governed by Discord's ``Use External Apps``
        permission, not ordinary ``Send Messages``.  For an app without a
        guild/bot installation, Discord does not reliably expose that server
        decision in ``app_permissions``; it enforces the final visibility
        itself.  A guild-installed app uses its normal contextual send
        permission.  DMs and private channels do not need a guild permission.
        """

        if getattr(interaction, "guild_id", None) is None:
            return True

        permissions = getattr(interaction, "app_permissions", None)
        user_install = "1" in owners or 1 in owners
        guild_install = "0" in owners or 0 in owners
        if user_install and not guild_install:
            del permissions
            return True
        return bool(getattr(permissions, "send_messages", False))

    @staticmethod
    def _message_context(message: Any) -> MessageContext:
        """Normalize the resolved message supplied by a message command."""

        reference = getattr(message, "reference", None)
        attachments = tuple(
            AttachmentRef(
                attachment_id=str(attachment.id),
                source_url=str(attachment.url),
                filename=str(attachment.filename),
                declared_content_type=getattr(attachment, "content_type", None),
                declared_size=int(getattr(attachment, "size", 0)),
            )
            for attachment in getattr(message, "attachments", ())
        )
        author = message.author
        avatar = getattr(author, "display_avatar", None)
        avatar_url = getattr(avatar, "url", None)

        return MessageContext(
            message_id=int(message.id),
            author_id=int(author.id),
            author_name=getattr(author, "display_name", getattr(author, "name", "unknown")),
            content=str(getattr(message, "content", "")),
            channel_id=getattr(message, "channel", None) and getattr(message.channel, "id", None),
            guild_id=getattr(message, "guild", None) and getattr(message.guild, "id", None),
            reply_to_message_id=getattr(reference, "message_id", None),
            attachments=attachments,
            author_avatar_url=str(avatar_url) if avatar_url is not None else None,
        )

    @staticmethod
    def _attachment_ref(attachment: Any) -> AttachmentRef:
        """Normalize one slash-command attachment without retaining the Discord object."""

        return AttachmentRef(
            attachment_id=str(attachment.id),
            source_url=str(attachment.url),
            filename=str(attachment.filename),
            declared_content_type=getattr(attachment, "content_type", None),
            declared_size=int(getattr(attachment, "size", 0)),
        )

    @staticmethod
    def _user_context(user: Any) -> UserContext:
        """Normalize a resolved Discord user for a user context command."""

        avatar = getattr(user, "display_avatar", None)
        avatar_url = getattr(avatar, "url", None)
        return UserContext(
            user_id=int(user.id),
            display_name=str(getattr(user, "display_name", getattr(user, "name", "unknown"))),
            avatar_url=str(avatar_url) if avatar_url is not None else None,
        )
