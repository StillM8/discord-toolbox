from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

import pytest
from openai_codex import ApprovalMode, ImageInput, Sandbox, TextInput

from toolbox.core.errors import ProviderUnavailable
from toolbox.core.models import AIProfile, LLMRequest, LLMResponse
from toolbox.providers.llm.codex import CodexProvider
from toolbox.providers.llm.router import AIRouter


class FakeTurn:
    final_response = "Codex answer"
    usage = None


class FakeThread:
    def __init__(self, response: str = "Codex answer") -> None:
        self.response = response
        self.input: str | list[TextInput | ImageInput] | None = None
        self.effort: str | None = None
        self.model: str | None = None
        self.output_schema: Mapping[str, object] | None = None
        self.sandbox: Sandbox | None = None

    async def run(
        self,
        input: str | list[TextInput | ImageInput],
        *,
        effort: str | None = None,
        model: str | None = None,
        output_schema: Mapping[str, object] | None = None,
        sandbox: Sandbox | None = None,
    ) -> FakeTurn:
        self.input = input
        self.effort = effort
        self.model = model
        self.output_schema = output_schema
        self.sandbox = sandbox
        turn = FakeTurn()
        turn.final_response = self.response
        return turn


class FakeClient:
    def __init__(self) -> None:
        self.thread = FakeThread()
        self.approval_mode: ApprovalMode | None = None
        self.base_instructions: str | None = None
        self.cwd: str | None = None
        self.ephemeral: bool | None = None
        self.model: str | None = None
        self.sandbox: Sandbox | None = None
        self.closed = False

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
        self.approval_mode = approval_mode
        self.base_instructions = base_instructions
        self.cwd = cwd
        self.ephemeral = ephemeral
        self.model = model
        self.sandbox = sandbox
        return self.thread

    async def close(self) -> None:
        self.closed = True


class FakeDeviceLoginHandle:
    verification_url = "https://auth.openai.com/device"
    user_code = "ABCD-EFGH"

    def __init__(self) -> None:
        self.completed = False

    async def wait(self) -> object:
        self.completed = True
        return None


class FakeAuthenticationClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.login_handle = FakeDeviceLoginHandle()

    async def login_chatgpt_device_code(self) -> FakeDeviceLoginHandle:
        return self.login_handle


@pytest.mark.asyncio
async def test_codex_provider_is_ephemeral_read_only_and_normalized() -> None:
    client = FakeClient()
    provider = CodexProvider(client=client, model="gpt-5.6-luna")

    response = await provider.generate(LLMRequest(system="Be concise", input="hello"))

    assert response.text == "Codex answer"
    assert client.approval_mode is ApprovalMode.deny_all
    assert client.ephemeral is True
    assert client.sandbox is Sandbox.read_only
    assert client.model == "gpt-5.6-luna"
    assert client.base_instructions == "Be concise"
    assert client.thread.effort == "medium"
    assert client.thread.sandbox is Sandbox.read_only
    assert isinstance(client.thread.input, str)
    assert "USER INPUT" in client.thread.input

    await provider.close()
    assert client.closed is True


@pytest.mark.asyncio
async def test_codex_provider_normalizes_structured_output() -> None:
    client = FakeClient()
    client.thread = FakeThread('{"verdict":"true"}')
    provider = CodexProvider(client=client)

    response = await provider.generate(
        LLMRequest(
            system=None,
            input="classify this",
            response_schema={"type": "object"},
        )
    )

    assert response.structured == {"verdict": "true"}


@pytest.mark.asyncio
async def test_ai_router_falls_back_without_exposing_provider_choice() -> None:
    class Primary:
        async def generate(self, request: LLMRequest) -> LLMResponse:
            raise ProviderUnavailable

    class Fallback:
        async def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(text="fallback")

    router = AIRouter(
        profiles={AIProfile.NORMAL: "codex-normal"},
        providers={"codex-normal": Primary(), "responses": Fallback()},
        fallbacks={"codex-normal": "responses"},
    )

    response = await router.generate(AIProfile.NORMAL, LLMRequest(system=None, input="hello"))

    assert response.text == "fallback"


def test_codex_environment_does_not_forward_host_home() -> None:
    environment = getattr(CodexProvider, "_safe_environment")(
        {"HOME": "/host/home", "CODEX_HOME": "/isolated/codex", "PATH": "/bin"}
    )

    assert environment == {"CODEX_HOME": "/isolated/codex", "PATH": "/bin"}


def test_codex_launch_uses_an_empty_environment_boundary() -> None:
    provider = CodexProvider(
        client=FakeClient(),
        environment={"CODEX_HOME": "/isolated/codex", "PATH": "/safe/bin"},
    )

    launch = getattr(provider, "_launch_args_override")
    assert launch is not None
    assert "-i" in launch
    assert "CODEX_HOME=/isolated/codex" in launch
    assert "HOME=/isolated/codex" in launch
    assert "PATH=/safe/bin" in launch
    assert not any("DISCORD_TOKEN" in item for item in launch)
    assert not any("OPENAI_API_KEY" in item for item in launch)


@pytest.mark.asyncio
async def test_codex_provider_exposes_device_login_and_refreshes_health(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    client = FakeAuthenticationClient()
    refreshed = False

    async def refresh() -> None:
        nonlocal refreshed
        refreshed = True

    provider = CodexProvider(
        client=client,
        environment={"CODEX_HOME": str(codex_home)},
    )
    provider.set_authentication_callback(refresh)

    first = await provider.begin_device_login()
    second = await provider.begin_device_login()

    assert first == second
    assert first.verification_url == "https://auth.openai.com/device"
    assert first.user_code == "ABCD-EFGH"

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert client.login_handle.completed is True
    assert refreshed is True
    await provider.close()
