from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from toolbox.capabilities.codex_login import CodexLoginCapability
from toolbox.core.models import (
    ActorContext,
    AuthenticationChallenge,
    CapabilityName,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)


class FakeAuthenticationService:
    async def begin_device_login(self) -> AuthenticationChallenge:
        return AuthenticationChallenge(
            challenge_id=uuid4(),
            verification_url="https://auth.openai.com/device",
            user_code="ABCD-EFGH",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )


def _request(user_id: int) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.CODEX_LOGIN,
        actor=ActorContext(user=UserContext(user_id=user_id, display_name="tester")),
        interaction=InteractionContext(
            guild_id=None,
            channel_id=None,
            surface="private_channel",
        ),
    )


@pytest.mark.asyncio
async def test_codex_login_is_owner_only_and_returns_safe_device_link() -> None:
    capability = CodexLoginCapability(FakeAuthenticationService(), owner_id=42)

    denied = await capability.execute(_request(7))
    assert getattr(denied, "code", None) == "permission_denied"

    result = await capability.execute(_request(42))
    assert isinstance(result, TextResult)
    assert "https://auth.openai.com/device" in result.text
    assert "ABCD-EFGH" in result.text
