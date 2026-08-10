"""Explicit unavailable adapter when optional audio credentials are absent."""

from __future__ import annotations

from toolbox.core.contracts import TranscriptionProvider
from toolbox.core.errors import ProviderUnavailable
from toolbox.core.models import AssetRef, TranscriptionResult


class UnavailableTranscriptionProvider(TranscriptionProvider):
    """Keep transcription routable while explaining missing deployment support safely."""

    async def transcribe(self, asset: AssetRef) -> TranscriptionResult:
        del asset
        raise ProviderUnavailable
