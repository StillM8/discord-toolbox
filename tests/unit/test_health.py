from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from toolbox.capabilities.status import StatusCapability
from toolbox.core.models import (
    ActorContext,
    CapabilityName,
    HealthState,
    InteractionContext,
    TextResult,
    ToolRequest,
    UserContext,
)
from toolbox.infrastructure.health import RuntimeHealthService


def request(user_id: int) -> ToolRequest:
    return ToolRequest(
        request_id=uuid4(),
        capability=CapabilityName.STATUS,
        actor=ActorContext(user=UserContext(user_id=user_id, display_name="Tester")),
        interaction=InteractionContext(guild_id=None, channel_id=None, surface="dm"),
    )


@pytest.mark.asyncio
async def test_status_is_owner_only(tmp_path: Path) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    service = RuntimeHealthService(
        http=client,
        searxng_url="http://searxng:8080",
        asset_directory=tmp_path,
        codex_home=tmp_path / "codex",
        codex_command="codex",
        openai_configured=False,
        paid_image_fallback_enabled=False,
        transcription_enabled=False,
    )
    try:
        result = await StatusCapability(service, owner_id=42).execute(request(7))
    finally:
        await client.aclose()

    assert result.__class__.__name__ == "ErrorResult"


@pytest.mark.asyncio
async def test_status_reports_sanitized_component_states(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/"
        return httpx.Response(200, text="SearXNG")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = RuntimeHealthService(
        http=client,
        searxng_url="http://searxng:8080",
        asset_directory=tmp_path,
        codex_home=tmp_path / "codex",
        codex_command="codex",
        openai_configured=False,
        paid_image_fallback_enabled=False,
        transcription_enabled=False,
    )
    service.set_component("SQLite", HealthState.HEALTHY, "schema ready")
    try:
        result = await StatusCapability(service, owner_id=42).execute(request(42))
    finally:
        await client.aclose()

    assert isinstance(result, TextResult)
    assert "SQLite" in result.text
    assert "SearXNG" in result.text
    assert "schema ready" in result.text
    assert "secret" not in result.text.lower()


@pytest.mark.asyncio
async def test_status_reports_local_transcription_without_openai(tmp_path: Path) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))
    )
    service = RuntimeHealthService(
        http=client,
        searxng_url="http://searxng:8080",
        asset_directory=tmp_path,
        codex_home=tmp_path / "codex",
        codex_command="codex",
        openai_configured=False,
        paid_image_fallback_enabled=False,
        transcription_enabled=True,
        local_transcription_enabled=True,
    )
    try:
        report = await service.snapshot()
    finally:
        await client.aclose()

    transcription = next(check for check in report.checks if check.name == "Transcription")
    assert transcription.state is HealthState.HEALTHY


@pytest.mark.asyncio
async def test_status_distinguishes_codex_text_from_imagegen(tmp_path: Path) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))
    )
    service = RuntimeHealthService(
        http=client,
        searxng_url="http://searxng:8080",
        asset_directory=tmp_path,
        codex_home=tmp_path / "codex",
        codex_command="codex",
        openai_configured=False,
        paid_image_fallback_enabled=False,
        transcription_enabled=False,
    )
    service.set_codex_probe(HealthState.HEALTHY, "text probe succeeded")
    service.set_codex_image_probe(HealthState.UNAVAILABLE, "artifact was unavailable")
    try:
        report = await service.snapshot()
    finally:
        await client.aclose()

    codex = next(check for check in report.checks if check.name == "Codex")
    image = next(check for check in report.checks if check.name == "Image generation")
    assert codex.state is HealthState.HEALTHY
    assert image.state is HealthState.UNAVAILABLE
