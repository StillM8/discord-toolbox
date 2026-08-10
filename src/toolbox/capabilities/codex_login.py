"""Owner-only Codex device authentication capability."""

from __future__ import annotations

from toolbox.core.contracts import AIAuthenticationService
from toolbox.core.errors import ToolboxError
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class CodexLoginCapability:
    """Return a private link/code without exposing provider details to Discord."""

    def __init__(self, auth: AIAuthenticationService, *, owner_id: int) -> None:
        self._auth = auth
        self._owner_id = owner_id

    async def execute(self, request: ToolRequest) -> ToolResult:
        if self._owner_id <= 0 or request.actor.user.user_id != self._owner_id:
            return ErrorResult(
                code="permission_denied",
                message="Only the configured Toolbox owner can start Codex authentication.",
            )

        try:
            challenge = await self._auth.begin_device_login()
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )

        safe_code = challenge.user_code.replace("`", "")
        return TextResult(
            title="Codex authentication",
            text=(
                f"[Open the Codex verification page]({challenge.verification_url})\n\n"
                f"Device code: `{safe_code}`\n\n"
                "Approve the login, wait a few seconds, then run `/me status`."
            ),
        )
