from __future__ import annotations

import pytest

from toolbox.core.errors import AssetRejected
from toolbox.infrastructure.url_policy import RemoteUrlPolicy


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/private",
        "https://10.0.0.5/private",
        "https://[::1]/private",
        "https://metadata.google.internal/computeMetadata/v1",
        "https://user:password@example.com/data",
    ],
)
def test_remote_url_policy_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(AssetRejected):
        RemoteUrlPolicy().validate(url)


def test_remote_url_policy_allows_https_public_host() -> None:
    RemoteUrlPolicy().validate("https://cdn.example/image.png")


@pytest.mark.asyncio
async def test_remote_url_policy_rejects_private_dns_answer() -> None:
    policy = RemoteUrlPolicy(resolver=lambda host, port: ("10.0.0.8",))

    with pytest.raises(AssetRejected):
        await policy.validate_network_target("https://public.example/image.png")


@pytest.mark.asyncio
async def test_remote_url_policy_accepts_public_dns_answer() -> None:
    policy = RemoteUrlPolicy(resolver=lambda host, port: ("93.184.216.34",))

    await policy.validate_network_target("https://public.example/image.png")
