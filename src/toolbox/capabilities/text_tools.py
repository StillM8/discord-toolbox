"""Small deterministic text transformations for quick Discord utility work."""

from __future__ import annotations

import re
import unicodedata

from toolbox.core.actions import share_action
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class TextCapability:
    """Transform bounded text without using a model for mechanical operations."""

    _modes = {
        "count",
        "upper",
        "lower",
        "title",
        "reverse",
        "trim",
        "slug",
        "sort",
        "dedupe",
    }

    async def execute(self, request: ToolRequest) -> ToolResult:
        mode = request.options.get("mode", "count").strip().lower()
        value = (request.text or request.options.get("value", "")).strip()
        if mode not in self._modes or not value or len(value) > 10_000:
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message=(
                    "Choose count, upper, lower, title, reverse, trim, slug, sort, or dedupe "
                    "and provide text up to 10,000 characters."
                ),
            )
        output = self._transform(mode, value)
        return TextResult(
            title=f"Text · {mode}",
            text=output,
            input_text=value,
            actions=(share_action(),),
        )

    @staticmethod
    def _transform(mode: str, value: str) -> str:
        if mode == "count":
            words = re.findall(r"\S+", value)
            lines = value.splitlines() or [value]
            return f"Characters: {len(value)}\nWords: {len(words)}\nLines: {len(lines)}"
        if mode == "upper":
            return value.upper()
        if mode == "lower":
            return value.lower()
        if mode == "title":
            return value.title()
        if mode == "reverse":
            return value[::-1]
        if mode == "trim":
            return " ".join(value.split())
        if mode == "slug":
            normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
            return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalized.lower())).strip("-")
        if mode == "sort":
            return "\n".join(sorted(value.splitlines(), key=str.casefold))
        if mode == "dedupe":
            seen: set[str] = set()
            lines: list[str] = []
            for line in value.splitlines():
                key = line.casefold()
                if key not in seen:
                    seen.add(key)
                    lines.append(line)
            return "\n".join(lines)
        raise InvalidRequest
