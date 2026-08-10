"""OpenAI Responses adapter used for fallback and vision profiles."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Awaitable
from typing import Any, Protocol, cast

from toolbox.core.contracts import AssetStore, LLMProvider
from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import LLMRequest, LLMResponse, UsageInfo


class ResponsesResource(Protocol):
    async def create(self, **kwargs: Any) -> Any:
        """Create one Responses API response."""

        ...


class OpenAIClient(Protocol):
    responses: ResponsesResource


class OpenAIResponsesProvider(LLMProvider):
    """Keep OpenAI SDK objects inside the provider boundary."""

    def __init__(
        self,
        *,
        client: OpenAIClient,
        model: str,
        assets: AssetStore | None = None,
        timeout_seconds: float = 90.0,
    ) -> None:
        self._client = client
        self._model = model
        self._assets = assets
        self._timeout_seconds = timeout_seconds

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self._model or not request.input.strip():
            raise InvalidRequest
        payload: dict[str, Any] = {
            "model": self._model,
            "instructions": request.system,
            "input": await self._input(request),
            "store": False,
        }
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "toolbox_structured_output",
                    "schema": dict(request.response_schema),
                    "strict": True,
                }
            }
        try:
            response_awaitable = cast(
                Awaitable[Any],
                self._client.responses.create(**payload),
            )
            response = await asyncio.wait_for(
                response_awaitable,
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            raise ProviderTimeout from error
        except Exception as error:
            status_code = getattr(error, "status_code", None)
            if status_code == 429:
                raise RateLimited from error
            raise ProviderUnavailable from error

        text = str(getattr(response, "output_text", "")).strip()
        if not text:
            raise ProviderUnavailable
        structured: object | None = None
        if request.response_schema is not None:
            try:
                structured = json.loads(text)
            except json.JSONDecodeError as error:
                raise ProviderUnavailable from error
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            structured=structured,
            usage=(
                UsageInfo(
                    input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                )
                if usage is not None
                else None
            ),
            provider_metadata={"provider": "openai_responses", "model": self._model},
        )

    async def _input(self, request: LLMRequest) -> str | list[dict[str, object]]:
        if not request.images:
            return request.input
        if self._assets is None:
            raise InvalidRequest
        content: list[dict[str, object]] = [{"type": "input_text", "text": request.input}]
        for asset in request.images:
            data = await self._assets.read(asset)
            encoded = base64.b64encode(data).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{asset.mime_type};base64,{encoded}",
                }
            )
        return [{"role": "user", "content": content}]
