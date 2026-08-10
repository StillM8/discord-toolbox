from __future__ import annotations

from uuid import uuid4

import pytest

from toolbox.capabilities.user_info import UserInfoCapability
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)


@pytest.mark.asyncio
async def test_user_info_uses_only_normalized_target_data() -> None:
    result = await UserInfoCapability().execute(
        ToolRequest(
            request_id=uuid4(),
            capability=CapabilityName.USER_INFO,
            actor=ActorContext(user=UserContext(user_id=1, display_name="Owner")),
            interaction=InteractionContext(None, None, "dm"),
            target_user=UserContext(
                user_id=2,
                display_name="Target",
                avatar_url="https://cdn.example/avatar.png",
            ),
        )
    )

    assert isinstance(result, TextResult)
    assert "2" in result.text
    assert "https://cdn.example/avatar.png" in result.text
