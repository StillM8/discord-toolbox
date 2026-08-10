"""Encoding, decoding, hashing, and checksum utilities."""

from __future__ import annotations

import base64
import binascii
import hashlib
from urllib.parse import quote, unquote

from toolbox.core.actions import share_action
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class EncodingCapability:
    """Perform bounded standard-library encoding operations."""

    _hashes = {"md5", "sha1", "sha224", "sha256", "sha384", "sha512"}
    _modes = {
        "base64_encode",
        "base64_decode",
        "url_encode",
        "url_decode",
        "hex_encode",
        "hex_decode",
        "hash",
    }

    async def execute(self, request: ToolRequest) -> ToolResult:
        mode = request.options.get("mode", "hash").strip().lower()
        value = request.text or request.options.get("value", "")
        if mode not in self._modes or not value or len(value) > 20_000:
            error = InvalidRequest
            return ErrorResult(
                code=error.code,
                message=(
                    "Choose base64_encode, base64_decode, url_encode, url_decode, "
                    "hex_encode, hex_decode, or hash."
                ),
            )
        try:
            output = self._transform(mode, value, request.options.get("algorithm", "sha256"))
        except (InvalidRequest, UnicodeDecodeError, binascii.Error, ValueError) as error:
            if not isinstance(error, InvalidRequest):
                error = InvalidRequest
            return ErrorResult(code=error.code, message="That value could not be encoded safely.")
        return TextResult(
            title=f"Encoding · {mode}",
            text=output,
            input_text=value,
            actions=(share_action(),),
        )

    @classmethod
    def _transform(cls, mode: str, value: str, algorithm: str) -> str:
        if mode == "base64_encode":
            return base64.b64encode(value.encode("utf-8")).decode("ascii")
        if mode == "base64_decode":
            return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8")
        if mode == "url_encode":
            return quote(value, safe="")
        if mode == "url_decode":
            return unquote(value)
        if mode == "hex_encode":
            return value.encode("utf-8").hex()
        if mode == "hex_decode":
            return bytes.fromhex(value).decode("utf-8")
        if mode == "hash":
            normalized = algorithm.strip().lower()
            if normalized not in cls._hashes:
                raise InvalidRequest
            return hashlib.new(normalized, value.encode("utf-8")).hexdigest()
        raise InvalidRequest
