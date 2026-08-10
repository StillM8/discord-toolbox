"""Safe information returned by a Discord user context action."""

from __future__ import annotations

from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class UserInfoCapability:
    """Return only normalized target-user facts supplied by Discord."""

    async def execute(self, request: ToolRequest) -> ToolResult:
        target = request.target_user
        if target is None:
            return ErrorResult(code="invalid_request", message="Select a user first.")
        avatar = f"\nAvatar: {target.avatar_url}" if target.avatar_url else ""
        return TextResult(
            title=f"User · {target.display_name}",
            text=f"Discord user ID: `{target.user_id}`{avatar}",
        )
