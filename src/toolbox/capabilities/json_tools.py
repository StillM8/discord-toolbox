"""Safe JSON formatting and validation utilities."""

from __future__ import annotations

import json

from toolbox.core.actions import share_action
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class JsonCapability:
    """Format, minify, sort, or validate JSON without executing its contents."""

    _modes = {"format", "minify", "sort", "validate"}

    async def execute(self, request: ToolRequest) -> ToolResult:
        mode = request.options.get("mode", "format").strip().lower()
        value = request.text or request.options.get("value", "")
        if mode not in self._modes or not value or len(value) > 50_000:
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message="Choose format, minify, sort, or validate and provide valid JSON text.",
            )
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            return ErrorResult(
                code="invalid_json",
                message=f"Invalid JSON near line {error.lineno}, column {error.colno}.",
            )
        if mode == "validate":
            output = "Valid JSON."
        elif mode == "minify":
            output = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        else:
            output = json.dumps(
                parsed,
                ensure_ascii=False,
                indent=2,
                sort_keys=mode == "sort",
            )
        return TextResult(
            title=f"JSON · {mode}",
            text=output,
            input_text=value,
            actions=(share_action(),),
        )
