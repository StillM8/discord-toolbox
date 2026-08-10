"""Profile-based AI routing with explicit provider fallback."""

from __future__ import annotations

from collections.abc import Mapping

from toolbox.core.contracts import AIService, LLMProvider
from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import AIProfile, LLMRequest, LLMResponse


class AIRouter(AIService):
    """Choose a configured provider for an application intent."""

    def __init__(
        self,
        *,
        profiles: Mapping[AIProfile, str],
        providers: Mapping[str, LLMProvider],
        fallbacks: Mapping[str, str] | None = None,
    ) -> None:
        self._profiles = dict(profiles)
        self._providers = dict(providers)
        self._fallbacks = dict(fallbacks or {})

    async def generate(self, profile: AIProfile, request: LLMRequest) -> LLMResponse:
        provider_name = self._profiles.get(profile)
        if provider_name is None:
            raise InvalidRequest
        provider = self._providers.get(provider_name)
        if provider is None:
            raise InvalidRequest
        try:
            return await provider.generate(request)
        except (ProviderUnavailable, ProviderTimeout, RateLimited):
            fallback_name = self._fallbacks.get(provider_name)
            fallback = self._providers.get(fallback_name) if fallback_name else None
            if fallback is None:
                raise
            return await fallback.generate(request)
