"""Bounded randomization utilities that never delegate deterministic work to AI."""

from __future__ import annotations

import random
import re
import secrets
import string
from uuid import uuid4

from toolbox.core.actions import share_action
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class RandomCapability:
    """Provide safe dice, coin, range, choice, password, and UUID utilities."""

    _dice = re.compile(r"^(?P<count>\d+)?\s*d\s*(?P<sides>\d+)$", re.IGNORECASE)
    _range = re.compile(r"^(?P<low>-?\d+)\s*(?:to|\.\.|-)\s*(?P<high>-?\d+)$")
    _password_alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    async def execute(self, request: ToolRequest) -> ToolResult:
        mode, value = self._mode_and_value(request)
        try:
            text, title, shareable = self._run(mode, value)
        except InvalidRequest as error:
            return ErrorResult(
                code=error.code,
                message=(
                    "Choose coin, dice, number, choose, password, or uuid. "
                    "Examples: `2d20`, `1-100`, or `pizza | burger`."
                ),
            )
        return TextResult(
            title=title,
            text=text,
            input_text=value or mode,
            actions=(share_action(),) if shareable else (),
        )

    def _run(self, mode: str, value: str) -> tuple[str, str, bool]:
        normalized = mode.strip().lower().replace("-", "_")
        if normalized in {"coin", "flip"}:
            return self._rng.choice(("Heads", "Tails")), "Coin flip", True
        if normalized in {"dice", "roll"}:
            return self._dice_roll(value)
        if normalized in {"number", "range", "random_number"}:
            return str(self._random_number(value)), "Random number", True
        if normalized in {"choose", "choice", "pick"}:
            choices = [item.strip() for item in re.split(r"\s*\|\s*", value) if item.strip()]
            if not 2 <= len(choices) <= 50 or any(len(item) > 200 for item in choices):
                raise InvalidRequest
            return self._rng.choice(choices), "Random choice", True
        if normalized in {"password", "pass"}:
            length = self._password_length(value)
            password = "".join(secrets.choice(self._password_alphabet) for _ in range(length))
            # Passwords are deliberately not shareable by default.
            return password, "Generated password", False
        if normalized in {"uuid", "id"}:
            return str(uuid4()), "UUID", True
        raise InvalidRequest

    def _dice_roll(self, value: str) -> tuple[str, str, bool]:
        match = self._dice.fullmatch(value.strip() or "1d20")
        if match is None:
            raise InvalidRequest
        count = int(match.group("count") or "1")
        sides = int(match.group("sides"))
        if not 1 <= count <= 20 or not 2 <= sides <= 1_000:
            raise InvalidRequest
        rolls = [self._rng.randint(1, sides) for _ in range(count)]
        return (
            f"Rolls: {', '.join(str(roll) for roll in rolls)}\nTotal: {sum(rolls)}",
            "Dice roll",
            True,
        )

    def _random_number(self, value: str) -> int:
        normalized = value.strip() or "1-100"
        match = self._range.fullmatch(normalized)
        if match is None:
            try:
                high = int(normalized)
            except ValueError as error:
                raise InvalidRequest from error
            low = 1
        else:
            low = int(match.group("low"))
            high = int(match.group("high"))
        if low > high:
            low, high = high, low
        if low < -1_000_000_000 or high > 1_000_000_000:
            raise InvalidRequest
        return self._rng.randint(low, high)

    @staticmethod
    def _password_length(value: str) -> int:
        try:
            length = int(value.strip() or "16")
        except ValueError as error:
            raise InvalidRequest from error
        if not 8 <= length <= 128:
            raise InvalidRequest
        return length

    @staticmethod
    def _mode_and_value(request: ToolRequest) -> tuple[str, str]:
        value = (request.text or request.options.get("value", "")).strip()
        mode = request.options.get("mode", "").strip().lower()
        if not mode and value:
            first, separator, remainder = value.partition(" ")
            if first.lower() in {
                "coin",
                "dice",
                "roll",
                "number",
                "range",
                "choose",
                "pick",
                "password",
                "uuid",
            }:
                mode = first
                value = remainder.strip() if separator else ""
        return mode or "coin", value
