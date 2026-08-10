from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai_codex import ApprovalMode, ImageInput, Sandbox, TextInput

from toolbox.core.errors import ProviderUnavailable
from toolbox.core.models import ImageGenerationRequest
from toolbox.providers.images.codex import CodexImageProvider
from toolbox.providers.llm.codex import CodexProvider

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeTurn:
    final_response = "OK"
    usage = None

    def __init__(self, image: bytes | None = None) -> None:
        self.items = (
            [SimpleNamespace(type="imageGeneration", result=base64.b64encode(image).decode())]
            if image is not None
            else []
        )


class FakeThread:
    async def run(
        self,
        input: str | list[TextInput | ImageInput],
        *,
        effort: str | None = None,
        model: str | None = None,
        output_schema: Mapping[str, object] | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeTurn:
        del input, effort, model, output_schema, sandbox
        return FakeTurn(_PNG)


class RecordingThread(FakeThread):
    def __init__(self) -> None:
        self.last_effort: str | None = None

    async def run(
        self,
        input: str | list[TextInput | ImageInput],
        *,
        effort: str | None = None,
        model: str | None = None,
        output_schema: Mapping[str, object] | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeTurn:
        self.last_effort = effort
        return await super().run(
            input,
            effort=effort,
            model=model,
            output_schema=output_schema,
            sandbox=sandbox,
        )


class FakeClient:
    async def thread_start(
        self,
        *,
        approval_mode: ApprovalMode,
        base_instructions: str | None,
        cwd: str | None,
        ephemeral: bool | None,
        model: str | None,
        sandbox: Sandbox | None,
    ) -> FakeThread:
        assert approval_mode is ApprovalMode.deny_all
        assert base_instructions is not None
        assert cwd is not None
        assert ephemeral is True
        assert model is not None
        assert sandbox is Sandbox.read_only
        return FakeThread()

    async def close(self) -> None:
        return None


class RecordingClient(FakeClient):
    def __init__(self) -> None:
        self.thread = RecordingThread()

    async def thread_start(
        self,
        *,
        approval_mode: ApprovalMode,
        base_instructions: str | None,
        cwd: str | None,
        ephemeral: bool | None,
        model: str | None,
        sandbox: Sandbox | None,
    ) -> RecordingThread:
        await super().thread_start(
            approval_mode=approval_mode,
            base_instructions=base_instructions,
            cwd=cwd,
            ephemeral=ephemeral,
            model=model,
            sandbox=sandbox,
        )
        return self.thread


class SlowImageThread(FakeThread):
    async def run(
        self,
        input: str | list[TextInput | ImageInput],
        *,
        effort: str | None = None,
        model: str | None = None,
        output_schema: Mapping[str, object] | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeTurn:
        await asyncio.sleep(0.02)
        return await super().run(
            input,
            effort=effort,
            model=model,
            output_schema=output_schema,
            sandbox=sandbox,
        )


class SlowImageClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.thread = SlowImageThread()


@pytest.mark.asyncio
async def test_codex_image_adapter_requires_and_normalizes_returned_artifact() -> None:
    backend = CodexProvider(client=FakeClient(), model="gpt-5.6-luna")
    provider = CodexImageProvider(backend)

    generated = await provider.generate(ImageGenerationRequest(prompt="a tiny blue square"))

    assert generated.data == _PNG
    assert generated.mime_type == "image/png"


@pytest.mark.asyncio
async def test_codex_image_operations_use_the_longer_media_timeout() -> None:
    backend = CodexProvider(
        client=SlowImageClient(),
        timeout_seconds=0.005,
        image_timeout_seconds=0.1,
    )

    generated = await backend.generate_image(ImageGenerationRequest(prompt="a tiny square"))

    assert generated.data == _PNG


@pytest.mark.asyncio
async def test_codex_image_operations_use_low_image_effort() -> None:
    client = RecordingClient()
    backend = CodexProvider(
        client=client,
        model="gpt-5.6-luna",
        effort="high",
        image_effort="low",
    )

    await backend.generate_image(ImageGenerationRequest(prompt="a tiny square"))

    assert client.thread.last_effort == "low"


@pytest.mark.asyncio
async def test_codex_image_adapter_rejects_oversized_artifacts() -> None:
    backend = CodexProvider(
        client=FakeClient(),
        model="gpt-5.6-luna",
        max_image_bytes=3,
    )

    with pytest.raises(ProviderUnavailable):
        await backend.generate_image(ImageGenerationRequest(prompt="a tiny blue square"))


@pytest.mark.asyncio
async def test_codex_probe_requires_an_explicit_persisted_codex_home(tmp_path: Path) -> None:
    authenticated_home = tmp_path / "codex"
    authenticated_home.mkdir()
    authenticated = CodexProvider(
        client=FakeClient(),
        environment={"CODEX_HOME": str(authenticated_home)},
    )
    unauthenticated = CodexProvider(
        client=FakeClient(),
        environment={"CODEX_HOME": str(tmp_path / "missing")},
    )

    assert await authenticated.probe(timeout_seconds=1)
    assert await authenticated.probe_image(timeout_seconds=1)
    assert not await unauthenticated.probe(timeout_seconds=1)
    assert not await unauthenticated.probe_image(timeout_seconds=1)
