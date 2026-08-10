"""Optional local background-removal provider backed by rembg."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from typing import Any, cast

from toolbox.core.errors import AssetRejected, ProviderUnavailable
from toolbox.core.models import GeneratedImage


class RembgBackgroundRemovalProvider:
    """Run rembg outside the event loop and return only validated PNG bytes."""

    def __init__(self, *, model: str = "u2net") -> None:
        self._model = model

    async def remove(self, data: bytes, mime_type: str) -> GeneratedImage:
        if not data or not mime_type.startswith("image/"):
            raise AssetRejected
        return await asyncio.to_thread(self._remove_sync, data)

    def _remove_sync(self, data: bytes) -> GeneratedImage:
        try:
            module = importlib.import_module("rembg")
        except ModuleNotFoundError as error:
            raise ProviderUnavailable from error
        try:
            new_session = cast(Callable[[str], Any], getattr(module, "new_session"))
            remove = cast(Callable[..., Any], getattr(module, "remove"))
            session: Any = new_session(self._model)
            output = cast(bytes, remove(data, session=session))
        except Exception as error:
            raise ProviderUnavailable from error
        if not output.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ProviderUnavailable
        return GeneratedImage(data=output, mime_type="image/png")
