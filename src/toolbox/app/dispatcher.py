"""Ingress dispatcher; not an internal service locator."""

from __future__ import annotations

from toolbox.core.contracts import Handler
from toolbox.core.models import CapabilityName, ErrorResult, ToolRequest, ToolResult


class Dispatcher:
    """Route normalized ingress requests to registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[CapabilityName, Handler] = {}

    def register(self, capability: CapabilityName, handler: Handler) -> None:
        """Register one ingress handler."""

        if capability in self._handlers:
            raise ValueError(f"Capability already registered: {capability}")
        self._handlers[capability] = handler

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute a handler selected by an external ingress request."""

        handler = self._handlers.get(request.capability)
        if handler is None:
            return ErrorResult(
                code="capability_not_found",
                message="That Toolbox action is not available.",
            )
        return await handler.execute(request)
