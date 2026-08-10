"""OpenAI audio-transcription adapter."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, cast

from toolbox.core.contracts import AssetStore, TranscriptionProvider
from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import AssetRef, TranscriptionResult


class AudioTranscriptionsResource(Protocol):
    async def create(self, **kwargs: Any) -> Any:
        """Create a transcription through the provider SDK."""

        ...


class AudioResource(Protocol):
    transcriptions: AudioTranscriptionsResource


class OpenAITranscriptionClient(Protocol):
    audio: AudioResource


class OpenAITranscriptionProvider(TranscriptionProvider):
    """Normalize OpenAI audio output into the application transcription contract."""

    def __init__(
        self,
        *,
        client: OpenAITranscriptionClient,
        assets: AssetStore,
        model: str = "gpt-4o-mini-transcribe",
        timeout_seconds: float = 120.0,
    ) -> None:
        self._client = client
        self._assets = assets
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def transcribe(self, asset: AssetRef) -> TranscriptionResult:
        if not self._model or not asset.mime_type.startswith("audio/"):
            raise InvalidRequest
        data = await self._assets.read(asset)
        try:
            response = await asyncio.wait_for(
                cast(Any, self._client.audio.transcriptions.create)(
                    model=self._model,
                    file=("toolbox-audio", data, asset.mime_type),
                    response_format="text",
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            raise ProviderTimeout from error
        except Exception as error:
            if getattr(error, "status_code", None) == 429:
                raise RateLimited from error
            raise ProviderUnavailable from error
        text = response if isinstance(response, str) else getattr(response, "text", "")
        if not isinstance(text, str) or not text.strip():
            raise ProviderUnavailable
        language = getattr(response, "language", None)
        return TranscriptionResult(
            text=text,
            language=language if isinstance(language, str) else None,
        )
