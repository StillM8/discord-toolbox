"""Optional local faster-whisper transcription provider."""

from __future__ import annotations

import asyncio
import importlib
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any

from toolbox.core.contracts import AssetStore, TranscriptionProvider
from toolbox.core.errors import ProviderUnavailable
from toolbox.core.models import AssetRef, TranscriptionResult


class FasterWhisperTranscriptionProvider(TranscriptionProvider):
    """Run a local Whisper model in a worker thread with lazy model loading."""

    def __init__(
        self,
        assets: AssetStore,
        *,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self._assets = assets
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Any | None = None
        self._model_lock = Lock()

    async def transcribe(self, asset: AssetRef) -> TranscriptionResult:
        data = await self._assets.read(asset)
        return await asyncio.to_thread(self._transcribe_sync, data, asset.mime_type)

    def _transcribe_sync(self, data: bytes, mime_type: str) -> TranscriptionResult:
        try:
            model = self._get_model()
            suffix = {
                "audio/mpeg": ".mp3",
                "audio/wav": ".wav",
                "audio/ogg": ".ogg",
                "audio/mp4": ".m4a",
                "video/mp4": ".mp4",
            }.get(mime_type, ".bin")
            with tempfile.TemporaryDirectory(prefix="toolbox-whisper-") as directory:
                path = Path(directory) / f"input{suffix}"
                path.write_bytes(data)
                segments, info = model.transcribe(str(path), beam_size=5)
                text = " ".join(str(segment.text).strip() for segment in segments).strip()
            return TranscriptionResult(
                text=text,
                language=str(getattr(info, "language", "")) or None,
            )
        except ProviderUnavailable:
            raise
        except Exception as error:
            raise ProviderUnavailable from error

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                module = importlib.import_module("faster_whisper")
            except ModuleNotFoundError as error:
                raise ProviderUnavailable from error
            whisper_model: Any = getattr(module, "WhisperModel")
            self._model = whisper_model(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
            return self._model
