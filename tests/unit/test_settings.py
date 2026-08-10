from __future__ import annotations

from pydantic import SecretStr

from toolbox.config.settings import Settings
from toolbox.core.models import AIProfile


def test_settings_keeps_codex_as_default_text_provider() -> None:
    settings = Settings(discord_token=SecretStr("test-token"))

    assert settings.ai_profiles[AIProfile.FAST].provider == "codex_fast"
    assert settings.ai_profiles[AIProfile.NORMAL].model == "gpt-5.6-luna"
    assert settings.ai_profiles[AIProfile.RESEARCH].effort == "high"
    assert settings.ai_profiles[AIProfile.VISION].provider == "openai_responses"
    assert settings.codex_timeout_seconds == 90.0
    assert settings.codex_image_timeout_seconds == 300.0
    assert settings.codex_image_effort == "low"
