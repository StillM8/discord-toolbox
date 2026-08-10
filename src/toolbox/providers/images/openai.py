"""OpenAI Images API adapter; SDK response types stay inside this module."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Protocol, cast

import httpx

from toolbox.core.contracts import AssetStore, ImageEditingProvider, ImageGenerationProvider
from toolbox.core.errors import InvalidRequest, ProviderTimeout, ProviderUnavailable, RateLimited
from toolbox.core.models import GeneratedImage, ImageEditRequest, ImageGenerationRequest
from toolbox.infrastructure.url_policy import RemoteUrlPolicy


class ImagesResource(Protocol):
    async def generate(self, **kwargs: Any) -> Any:
        """Create an image using the provider SDK."""

        ...

    async def edit(self, **kwargs: Any) -> Any:
        """Edit an image using the provider SDK."""

        ...


class OpenAIImagesClient(Protocol):
    images: ImagesResource


class OpenAIImageProvider(ImageGenerationProvider, ImageEditingProvider):
    """Normalize OpenAI image bytes into the application provider contract."""

    def __init__(
        self,
        *,
        client: OpenAIImagesClient,
        model: str,
        http: httpx.AsyncClient | None = None,
        assets: AssetStore | None = None,
        timeout_seconds: float = 180.0,
        url_policy: RemoteUrlPolicy | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._http = http
        self._assets = assets
        self._timeout_seconds = timeout_seconds
        self._url_policy = url_policy or RemoteUrlPolicy()

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        if not self._model or not request.prompt.strip() or len(request.prompt) > 8_000:
            raise InvalidRequest
        try:
            response = await asyncio.wait_for(
                cast(
                    Any,
                    self._client.images.generate(
                        model=self._model,
                        prompt=request.prompt,
                        size=request.size,
                        quality=request.quality,
                        n=1,
                    ),
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            raise ProviderTimeout from error
        except Exception as error:
            if getattr(error, "status_code", None) == 429:
                raise RateLimited from error
            raise ProviderUnavailable from error

        return await self._decode_response(response)

    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        """Edit one owned asset through the provider's image-edit endpoint."""

        if self._assets is None or not request.prompt.strip() or len(request.prompt) > 2_000:
            raise InvalidRequest
        data = await self._assets.read(request.asset)
        try:
            response = await asyncio.wait_for(
                cast(
                    Any,
                    self._client.images.edit(
                        model=self._model,
                        image=data,
                        prompt=request.prompt,
                        size=request.size,
                    ),
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            raise ProviderTimeout from error
        except Exception as error:
            if getattr(error, "status_code", None) == 429:
                raise RateLimited from error
            raise ProviderUnavailable from error
        return await self._decode_response(response)

    async def _decode_response(self, response: Any) -> GeneratedImage:
        data = getattr(response, "data", None)
        if not data:
            raise ProviderUnavailable
        first = data[0]
        encoded = getattr(first, "b64_json", None)
        if isinstance(encoded, str) and encoded:
            try:
                return GeneratedImage(base64.b64decode(encoded), "image/png")
            except ValueError as error:
                raise ProviderUnavailable from error
        url = getattr(first, "url", None)
        if isinstance(url, str) and self._http is not None:
            try:
                await self._url_policy.validate_network_target(url)
                fetched = await self._http.get(url)
            except httpx.TimeoutException as error:
                raise ProviderTimeout from error
            except httpx.HTTPError as error:
                raise ProviderUnavailable from error
            if fetched.status_code >= 400:
                raise ProviderUnavailable
            return GeneratedImage(fetched.content, fetched.headers.get("content-type", "image/png"))
        raise ProviderUnavailable
