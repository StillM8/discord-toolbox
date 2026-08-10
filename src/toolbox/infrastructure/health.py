"""Runtime health observations owned by the composition root."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import httpx

from toolbox.core.models import HealthCheck, HealthReport, HealthState


class RuntimeHealthService:
    """Collect lightweight, sanitized health information for owner diagnostics."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        searxng_url: str,
        asset_directory: Path,
        codex_home: Path,
        codex_command: str,
        openai_configured: bool,
        paid_image_fallback_enabled: bool,
        transcription_enabled: bool,
        local_transcription_enabled: bool = False,
        codex_image_generation_enabled: bool = False,
        giphy_configured: bool = False,
        background_removal_enabled: bool = False,
    ) -> None:
        self._http = http
        self._searxng_url = searxng_url.rstrip("/")
        self._asset_directory = asset_directory
        self._codex_home = codex_home
        self._codex_command = codex_command.split(maxsplit=1)[0] if codex_command else "codex"
        self._openai_configured = openai_configured
        self._paid_image_fallback_enabled = paid_image_fallback_enabled
        self._transcription_enabled = transcription_enabled
        self._local_transcription_enabled = local_transcription_enabled
        self._codex_image_generation_enabled = codex_image_generation_enabled
        self._giphy_configured = giphy_configured
        self._background_removal_enabled = background_removal_enabled
        self._codex_probe: HealthCheck | None = None
        self._codex_image_probe: HealthCheck | None = None
        self._components: dict[str, HealthCheck] = {
            "Discord": HealthCheck("Discord", HealthState.STARTING, "Gateway not connected"),
            "SQLite": HealthCheck("SQLite", HealthState.STARTING, "Startup pending"),
            "Assets": HealthCheck("Assets", HealthState.STARTING, "Startup pending"),
        }

    def set_component(self, name: str, state: HealthState, detail: str) -> None:
        """Record a bounded lifecycle observation."""

        self._components[name] = HealthCheck(name, state, detail[:200])

    def set_codex_probe(self, state: HealthState, detail: str) -> None:
        """Record the result of the optional authenticated startup probe."""

        check = HealthCheck("Codex", state, detail[:200])
        self._codex_probe = check

    def set_codex_image_probe(self, state: HealthState, detail: str) -> None:
        """Record whether Codex ImageGen returned a real retrievable artifact."""

        self._codex_image_probe = HealthCheck("Image generation", state, detail[:200])
        self._codex_image_generation_enabled = state is HealthState.HEALTHY

    async def snapshot(self) -> HealthReport:
        """Return current checks, probing only cheap local/internal dependencies."""

        checks = dict(self._components)
        checks["Codex"] = self._codex_check()
        checks["SearXNG"] = await self._searxng_check()
        checks["ffmpeg"] = self._binary_check("ffmpeg")
        checks["Tesseract"] = self._binary_check("tesseract")
        checks["OpenAI fallback"] = self._openai_check()
        checks["Image generation"] = self._image_generation_check()
        checks["Transcription"] = self._transcription_check()
        checks["GIPHY"] = self._giphy_check()
        checks["Background removal"] = self._background_removal_check()
        if not self._asset_directory.is_dir() or not os.access(self._asset_directory, os.W_OK):
            checks["Assets"] = HealthCheck(
                "Assets",
                HealthState.DEGRADED,
                "Asset directory is not writable",
            )
        return HealthReport(tuple(checks.values()))

    def _codex_check(self) -> HealthCheck:
        if self._codex_probe is not None:
            return self._codex_probe
        if not self._codex_home.exists():
            return HealthCheck(
                "Codex",
                HealthState.DEGRADED,
                "CODEX_HOME is not authenticated yet",
            )
        bundled_runtime = self._codex_command == "codex"
        if (
            not bundled_runtime
            and shutil.which(self._codex_command) is None
            and "CODEX_API_KEY" not in os.environ
        ):
            return HealthCheck(
                "Codex",
                HealthState.DEGRADED,
                "Codex runtime executable is unavailable",
            )
        return HealthCheck("Codex", HealthState.HEALTHY, "Codex state directory is available")

    async def _searxng_check(self) -> HealthCheck:
        try:
            # Check the private SearXNG service itself, not an upstream engine.
            # A real search can exceed a few seconds or be CAPTCHA-throttled while
            # the local aggregator remains healthy and reachable.
            response = await self._http.get(f"{self._searxng_url}/", timeout=3.0)
        except (httpx.HTTPError, TimeoutError):
            return HealthCheck("SearXNG", HealthState.UNAVAILABLE, "Search service is unreachable")
        if response.status_code >= 500:
            return HealthCheck(
                "SearXNG",
                HealthState.UNAVAILABLE,
                "Search service returned an error",
            )
        if response.status_code >= 400:
            return HealthCheck(
                "SearXNG",
                HealthState.DEGRADED,
                "Search service rejected the health check",
            )
        return HealthCheck(
            "SearXNG",
            HealthState.HEALTHY,
            "Internal search service responded",
        )

    @staticmethod
    def _binary_check(binary: str) -> HealthCheck:
        if shutil.which(binary) is None:
            return HealthCheck(binary, HealthState.UNAVAILABLE, "Executable is not installed")
        return HealthCheck(binary, HealthState.HEALTHY, "Executable is available")

    def _openai_check(self) -> HealthCheck:
        if not self._openai_configured:
            return HealthCheck(
                "OpenAI fallback",
                HealthState.DISABLED,
                "Optional API key/package not configured",
            )
        return HealthCheck(
            "OpenAI fallback",
            HealthState.HEALTHY,
            "Optional API client is configured",
        )

    def _image_generation_check(self) -> HealthCheck:
        if (
            self._codex_image_probe is not None
            and self._codex_image_probe.state is not HealthState.HEALTHY
        ):
            if not self._paid_image_fallback_enabled or not self._openai_configured:
                return self._codex_image_probe
        if self._codex_image_generation_enabled:
            detail = "Codex ImageGen is configured; artifact availability is checked per request"
            if self._paid_image_fallback_enabled and self._openai_configured:
                detail += "; paid fallback is also enabled"
            return HealthCheck("Image generation", HealthState.HEALTHY, detail)
        if not self._paid_image_fallback_enabled:
            return HealthCheck(
                "Image generation",
                HealthState.DISABLED,
                "Paid fallback is disabled",
            )
        if not self._openai_configured:
            return HealthCheck(
                "Image generation",
                HealthState.UNAVAILABLE,
                "No enabled image provider",
            )
        return HealthCheck("Image generation", HealthState.HEALTHY, "Paid fallback is configured")

    def _transcription_check(self) -> HealthCheck:
        if not self._transcription_enabled:
            return HealthCheck(
                "Transcription",
                HealthState.DISABLED,
                "Optional transcription is disabled",
            )
        if self._local_transcription_enabled:
            return HealthCheck(
                "Transcription",
                HealthState.HEALTHY,
                "Local faster-whisper transcription is configured",
            )
        if not self._openai_configured:
            return HealthCheck(
                "Transcription",
                HealthState.UNAVAILABLE,
                "No enabled transcription provider",
            )
        return HealthCheck(
            "Transcription",
            HealthState.HEALTHY,
            "Optional transcription is configured",
        )

    def _giphy_check(self) -> HealthCheck:
        if not self._giphy_configured:
            return HealthCheck(
                "GIPHY",
                HealthState.DISABLED,
                "Optional GIF search is not configured",
            )
        return HealthCheck("GIPHY", HealthState.HEALTHY, "Optional GIF search is configured")

    def _background_removal_check(self) -> HealthCheck:
        if not self._background_removal_enabled:
            return HealthCheck(
                "Background removal",
                HealthState.DISABLED,
                "Optional local background removal is not enabled",
            )
        return HealthCheck(
            "Background removal",
            HealthState.HEALTHY,
            "Optional local background removal is configured",
        )
