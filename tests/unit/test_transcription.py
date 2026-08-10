from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest

from toolbox.capabilities.transcribe import TranscribeCapability
from toolbox.core.models import (
    ActorContext,
    AssetRef,
    AttachmentRef,
    CapabilityName,
    ContextItem,
    InteractionContext,
    MessageContext,
    TextResult,
    ToolRequest,
    TranscriptionResult,
    UserContext,
)
from toolbox.providers.audio.openai import OpenAITranscriptionClient, OpenAITranscriptionProvider


class Assets:
    def __init__(self, data: bytes = b"audio") -> None:
        self.data = data
        self.asset = AssetRef(uuid4(), "audio/ogg", len(data), 42)

    async def put(
        self,
        data: bytes,
        *,
        owner_id: int,
        mime_type: str,
        ttl_seconds: int | None = None,
    ) -> AssetRef:
        del ttl_seconds
        self.data = data
        self.asset = AssetRef(uuid4(), mime_type, len(data), owner_id)
        return self.asset

    async def read(self, asset: AssetRef) -> bytes:
        assert asset.asset_id == self.asset.asset_id
        return self.data

    async def delete(self, asset: AssetRef) -> None:
        del asset


def request(
    *,
    asset: AssetRef | None = None,
    message: MessageContext | None = None,
    attachments: tuple[AttachmentRef, ...] = (),
) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.TRANSCRIBE,
        actor=ActorContext(user=UserContext(user_id=42, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="test"),
        target_message=message,
        attachments=attachments,
        context_items=(ContextItem(uuid4(), 42, "audio", asset=asset),) if asset else (),
    )


@pytest.mark.asyncio
async def test_transcribe_capability_uses_selected_audio_asset() -> None:
    assets = Assets()

    class Provider:
        async def transcribe(self, asset: AssetRef) -> TranscriptionResult:
            assert asset == assets.asset
            return TranscriptionResult("hello from audio", "en")

    result = await TranscribeCapability(Provider(), assets).execute(
        request(asset=assets.asset)
    )

    assert isinstance(result, TextResult)
    assert result.text == "hello from audio"


@pytest.mark.asyncio
async def test_transcribe_capability_downloads_raw_audio_attachment() -> None:
    audio = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 16

    class Ingestor:
        async def ingest_raw(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
            assert attachment.filename == "voice.wav"
            assert owner_id == 42
            return AssetRef(uuid4(), "audio/wav", len(audio), owner_id)

    class Provider:
        async def transcribe(self, asset: AssetRef) -> TranscriptionResult:
            assert asset.mime_type == "audio/wav"
            return TranscriptionResult("transcribed")

    message = MessageContext(
        message_id=1,
        author_id=7,
        author_name="Speaker",
        content="",
        channel_id=None,
        guild_id=None,
        reply_to_message_id=None,
        attachments=(
            AttachmentRef(
                "a",
                "https://cdn.example/voice.wav",
                "voice.wav",
                "audio/wav",
                len(audio),
            ),
        ),
    )
    result = await TranscribeCapability(Provider(), Assets(), Ingestor()).execute(
        request(message=message)
    )

    assert isinstance(result, TextResult)
    assert result.text == "transcribed"


@pytest.mark.asyncio
async def test_openai_transcription_provider_normalizes_text_response() -> None:
    class Transcriptions:
        async def create(self, **kwargs: object) -> str:
            assert kwargs["model"] == "gpt-4o-mini-transcribe"
            assert kwargs["response_format"] == "text"
            return "hello"

    class Audio:
        transcriptions = Transcriptions()

    class Client:
        audio = Audio()

    assets = Assets()
    provider = OpenAITranscriptionProvider(
        client=cast(OpenAITranscriptionClient, Client()),
        assets=assets,
    )
    result = await provider.transcribe(assets.asset)

    assert result.text == "hello"


@pytest.mark.asyncio
async def test_transcribe_capability_accepts_a_slash_command_attachment() -> None:
    class Ingestor:
        async def ingest_raw(self, attachment: AttachmentRef, owner_id: int) -> AssetRef:
            assert attachment.filename == "voice.wav"
            return AssetRef(uuid4(), "audio/wav", 32, owner_id)

    class Provider:
        async def transcribe(self, asset: AssetRef) -> TranscriptionResult:
            assert asset.mime_type == "audio/wav"
            return TranscriptionResult("from slash attachment")

    result = await TranscribeCapability(Provider(), Assets(), Ingestor()).execute(
        request(
            attachments=(
                AttachmentRef("a", "https://cdn.example/voice.wav", "voice.wav", "audio/wav", 32),
            )
        )
    )

    assert isinstance(result, TextResult)
    assert result.text == "from slash attachment"
