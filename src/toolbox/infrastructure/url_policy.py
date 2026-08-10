"""Small SSRF guard shared by remote-input adapters."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

from toolbox.core.errors import AssetRejected


class RemoteUrlPolicy:
    """Reject unsafe schemes, local names, and private DNS destinations."""

    _blocked_hosts = {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "host.docker.internal",
    }

    def __init__(
        self,
        resolver: Callable[[str, int], Sequence[str]] | None = None,
    ) -> None:
        self._resolver = resolver or self._resolve

    def validate(self, url: str) -> None:
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
        except ValueError as error:
            raise AssetRejected from error
        if (
            parsed.scheme not in {"http", "https"}
            or hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise AssetRejected
        normalized = hostname.rstrip(".").lower()
        if normalized in self._blocked_hosts or normalized.endswith((".local", ".internal")):
            raise AssetRejected
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError:
            return
        if self._is_blocked(address):
            raise AssetRejected

    async def validate_network_target(self, url: str) -> None:
        """Validate literal syntax and every address returned for the hostname."""

        self.validate(url)
        parsed = urlparse(url)
        hostname = parsed.hostname
        if hostname is None:
            raise AssetRejected
        try:
            addresses = await asyncio.to_thread(
                self._resolver,
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            )
        except (OSError, ValueError) as error:
            raise AssetRejected from error
        if not addresses:
            raise AssetRejected
        for value in addresses:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as error:
                raise AssetRejected from error
            if self._is_blocked(address):
                raise AssetRejected

    @staticmethod
    def _resolve(hostname: str, port: int) -> tuple[str, ...]:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        return tuple({str(record[4][0]) for record in records})

    @staticmethod
    def _is_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
