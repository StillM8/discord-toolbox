"""One-time interactive Codex ChatGPT account login for the Docker volume."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from openai_codex import AsyncCodex, CodexConfig

from toolbox.config.settings import Settings


async def _login(device_code: bool) -> None:
    settings = Settings()
    codex = AsyncCodex(
        config=CodexConfig(
            codex_bin=None if settings.codex_command == "codex" else settings.codex_command,
            env={"CODEX_HOME": str(settings.codex_home)},
        )
    )
    try:
        handle: Any = (
            await codex.login_chatgpt_device_code()
            if device_code
            else await codex.login_chatgpt()
        )
        if device_code:
            verification_url = getattr(handle, "verification_url", "")
            user_code = getattr(handle, "user_code", "")
            print(f"Open {verification_url} and enter code {user_code}.")
        else:
            print(f"Open this URL to authenticate Codex: {getattr(handle, 'auth_url', '')}")
        await handle.wait()
        print("Codex authentication completed.")
    finally:
        await codex.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Authenticate the persisted Toolbox Codex home.")
    parser.add_argument(
        "--device-code",
        action="store_true",
        help="Use device-code login, suitable for a headless server.",
    )
    args = parser.parse_args()
    asyncio.run(_login(args.device_code))


if __name__ == "__main__":
    main()
