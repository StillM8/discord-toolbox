"""Read-only metadata inspection for explicitly supplied Discord attachments."""

from __future__ import annotations

from urllib.parse import urlparse

from toolbox.core.actions import share_action
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import AttachmentRef, ErrorResult, TextResult, ToolRequest, ToolResult


class FileInfoCapability:
    """Describe an attachment without downloading or executing it."""

    async def execute(self, request: ToolRequest) -> ToolResult:
        attachment = self._attachment(request)
        if attachment is None:
            error = InvalidRequest
            return ErrorResult(code=error.code, message="Attach one file to inspect.")
        host = urlparse(attachment.source_url).hostname or "unknown host"
        text = (
            f"Filename: `{attachment.filename}`\n"
            f"Declared type: `{attachment.declared_content_type or 'unknown'}`\n"
            f"Declared size: `{self._size(attachment.declared_size)}`\n"
            f"Attachment host: `{host}`"
        )
        return TextResult(
            title="File information",
            text=text,
            input_text=attachment.filename,
            actions=(share_action(),),
        )

    @staticmethod
    def _attachment(request: ToolRequest) -> AttachmentRef | None:
        if request.attachments:
            return request.attachments[0]
        if request.target_message is not None and request.target_message.attachments:
            return request.target_message.attachments[0]
        return None

    @staticmethod
    def _size(value: int) -> str:
        if value < 1_024:
            return f"{value} B"
        if value < 1_024**2:
            return f"{value / 1_024:.1f} KiB"
        return f"{value / (1_024**2):.1f} MiB"
