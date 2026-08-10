"""Typed deployment configuration loaded once at startup."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from toolbox.core.models import AIProfile


class AIProfileSettings(BaseModel):
    """Deployment mapping for one application AI intent."""

    provider: str
    model: str
    effort: Literal["none", "low", "medium", "high", "max"] = "medium"


class Settings(BaseSettings):
    """Runtime configuration; user preferences belong in storage instead."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    discord_token: SecretStr = SecretStr("")
    discord_application_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("DISCORD_APPLICATION_ID", "APPLICATION_ID"),
    )
    owner_id: int = Field(
        default=0,
        validation_alias=AliasChoices("OWNER_DISCORD_ID", "OWNER_ID"),
    )
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/toolbox.sqlite3"
    asset_directory: Path = Field(
        default=Path("./data/assets"),
        validation_alias=AliasChoices("ASSET_DIRECTORY", "ASSET_ROOT"),
    )

    codex_command: str = "codex"
    codex_home: Path = Path("/data/codex")
    codex_timeout_seconds: float = Field(default=90.0, gt=0, le=600)
    codex_image_timeout_seconds: float = Field(default=300.0, gt=0, le=900)
    # Image generation/editing is latency-sensitive. Keep reasoning separate
    # from the text profile so normal/research settings cannot slow media work.
    codex_image_effort: Literal["none", "low", "medium", "high", "max"] = "low"
    max_codex_concurrency: int = Field(default=2, gt=0, le=20)
    codex_model: str = "gpt-5.6-luna"
    codex_profile: str | None = "toolbox"

    openai_api_key: SecretStr | None = None
    openai_fallback_enabled: bool = False
    openai_fallback_model: str = "gpt-5.6-luna"
    openai_vision_model: str = "gpt-5.6-luna"
    openai_image_model: str = "gpt-image-2"
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    enable_paid_image_fallback: bool = False
    enable_openai_transcription: bool = False

    searxng_url: str = "http://searxng:8080"
    default_timezone: str = "Asia/Karachi"

    enable_giphy: bool = False
    giphy_api_key: SecretStr | None = None
    enable_tmdb: bool = False
    tmdb_api_token: SecretStr | None = None
    enable_youtube_api: bool = False
    youtube_api_key: SecretStr | None = None
    enable_local_background_removal: bool = False
    enable_local_transcription: bool = False

    max_text_length: int = Field(default=8_000, gt=0, le=100_000)
    max_attachment_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    max_context_items: int = Field(default=12, gt=0, le=100)
    context_ttl_seconds: int = Field(default=1_800, gt=0)
    session_ttl_seconds: int = Field(default=1_800, gt=0)
    max_search_results: int = Field(default=5, gt=0, le=20)
    max_reminder_attempts: int = Field(default=3, gt=0, le=10)
    reminder_claim_timeout_seconds: int = Field(default=120, gt=0, le=86_400)

    @property
    def ai_profiles(self) -> dict[AIProfile, AIProfileSettings]:
        """Return model mappings while keeping model names out of features."""

        return {
            AIProfile.FAST: AIProfileSettings(
                provider="codex_fast",
                model=self.codex_model,
                effort="low",
            ),
            AIProfile.NORMAL: AIProfileSettings(
                provider="codex_normal",
                model=self.codex_model,
                effort="medium",
            ),
            AIProfile.RESEARCH: AIProfileSettings(
                provider="codex_research",
                model=self.codex_model,
                effort="high",
            ),
            AIProfile.VISION: AIProfileSettings(
                provider="openai_responses",
                model=self.openai_vision_model,
                effort="medium",
            ),
        }

    def discord_token_value(self) -> str:
        """Return the token or fail at the process boundary."""

        token = self.discord_token.get_secret_value().strip()
        if not token:
            raise RuntimeError("DISCORD_TOKEN is required")
        return token
