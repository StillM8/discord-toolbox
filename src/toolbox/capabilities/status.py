"""Owner-only runtime diagnostics capability."""

from __future__ import annotations

from toolbox.core.contracts import HealthService
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class StatusCapability:
    """Expose sanitized health observations to the configured application owner."""

    def __init__(self, health: HealthService, *, owner_id: int) -> None:
        self._health = health
        self._owner_id = owner_id

    async def execute(self, request: ToolRequest) -> ToolResult:
        if self._owner_id <= 0 or request.actor.user.user_id != self._owner_id:
            return ErrorResult(
                code="permission_denied",
                message="Runtime status is available only to the Toolbox owner.",
            )
        report = await self._health.snapshot()
        lines = [
            f"{check.state.value.title():<11} {check.name}: {check.detail}"
            for check in report.checks
        ]
        return TextResult(title="Toolbox status", text="\n".join(lines))
