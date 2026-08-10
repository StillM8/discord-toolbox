"""Phase 0 dummy capability."""

from __future__ import annotations

from toolbox.core.models import TextResult, ToolRequest


class PingCapability:
    """Prove that the application path is wired without integrations."""

    async def execute(self, request: ToolRequest) -> TextResult:
        """Return a generic result without inspecting transport objects."""

        del request
        return TextResult(title="Toolbox", text="Toolbox is online.")
