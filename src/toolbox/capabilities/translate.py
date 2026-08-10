"""Translation capability using a fast AI profile."""

from __future__ import annotations

from toolbox.core.actions import share_action
from toolbox.core.contracts import AIService
from toolbox.core.errors import InvalidRequest, ToolboxError
from toolbox.core.models import (
    AIProfile,
    ErrorResult,
    LLMRequest,
    TextResult,
    ToolRequest,
    ToolResult,
)


class TranslateCapability:
    """Translate explicit text or a selected message."""

    def __init__(self, ai: AIService) -> None:
        self._ai = ai

    async def execute(self, request: ToolRequest) -> ToolResult:
        text = request.text or (request.target_message.content if request.target_message else "")
        language = request.options.get("language", "English")
        source_language = request.options.get("source_language", "auto").strip()
        if (
            not text.strip()
            or len(text) > 20_000
            or not language.strip()
            or len(language) > 100
            or len(source_language) > 100
        ):
            return ErrorResult(code="invalid_request", message="Give me text to translate.")
        try:
            response = await self._ai.generate(
                AIProfile.NORMAL,
                LLMRequest(
                    system=(
                        "You are a professional translator. Detect the source language "
                        "yourself, including transliterated or romanized languages such "
                        "as Pashto. Translate the supplied text into the requested "
                        "language, preserving meaning, tone, slang, and uncertainty. "
                        "Do not assume Latin-script text is English. Return only the "
                        "natural translation; do not repeat the source, explain your "
                        "process, or add headings."
                    ),
                    input=(
                        f"SOURCE LANGUAGE: {source_language or 'auto-detect'}\n"
                        f"TARGET LANGUAGE: {language}\nTEXT:\n{text}"
                    ),
                    max_output_tokens=2_000,
                ),
            )
        except InvalidRequest as error:
            return ErrorResult(code=error.code, message="That translation request is not valid.")
        except ToolboxError as error:
            return ErrorResult(
                code=error.code,
                message=error.user_message,
                retryable=error.retryable,
            )
        translated = response.text.strip()
        if not translated or translated.casefold() == text.strip().casefold():
            return ErrorResult(
                code="translation_uncertain",
                message=(
                    "I couldn't confidently translate that text. Try again with the "
                    "source language named, for example `Pashto → English`."
                ),
            )
        return TextResult(
            title=f"Translation → {language}",
            text=translated,
            input_text=(
                f"From {source_language or 'auto-detect'} to {language}:\n{text}"
            ),
            actions=(share_action(),),
        )
