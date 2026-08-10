"""Deterministic, non-evaluating calculator capability."""

from __future__ import annotations

import ast
import math

from toolbox.core.actions import share_action
from toolbox.core.errors import InvalidRequest
from toolbox.core.models import ErrorResult, TextResult, ToolRequest, ToolResult


class SafeCalculator:
    """Evaluate a deliberately small arithmetic grammar without Python execution."""

    def evaluate(self, expression: str) -> int | float:
        """Parse and evaluate a bounded arithmetic expression."""

        if not expression.strip() or len(expression) > 500:
            raise InvalidRequest

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as error:
            raise InvalidRequest from error

        value = self._visit(tree.body, depth=0)
        if type(value) not in (int, float):
            raise InvalidRequest
        if not math.isfinite(float(value)) or abs(float(value)) > 1e100:
            raise InvalidRequest
        return value

    def _visit(self, node: ast.AST, *, depth: int) -> int | float:
        if depth > 40:
            raise InvalidRequest

        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool) or abs(float(node.value)) > 1e100:
                raise InvalidRequest
            return node.value

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._visit(node.operand, depth=depth + 1)
            return value if isinstance(node.op, ast.UAdd) else -value

        if isinstance(node, ast.BinOp):
            left = self._visit(node.left, depth=depth + 1)
            right = self._visit(node.right, depth=depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise InvalidRequest
            try:
                if isinstance(node.op, ast.Add):
                    result = left + right
                elif isinstance(node.op, ast.Sub):
                    result = left - right
                elif isinstance(node.op, ast.Mult):
                    result = left * right
                elif isinstance(node.op, ast.Div):
                    result = left / right
                elif isinstance(node.op, ast.FloorDiv):
                    result = left // right
                elif isinstance(node.op, ast.Mod):
                    result = left % right
                elif isinstance(node.op, ast.Pow):
                    result = left**right
                else:
                    raise InvalidRequest
            except (ArithmeticError, OverflowError, ZeroDivisionError) as error:
                raise InvalidRequest from error
            if type(result) not in (int, float):
                raise InvalidRequest
            if not math.isfinite(float(result)) or abs(result) > 1e100:
                raise InvalidRequest
            return result

        raise InvalidRequest


class CalculateCapability:
    """Calculate one expression and return a generic text result."""

    def __init__(self, calculator: SafeCalculator | None = None) -> None:
        self._calculator = calculator or SafeCalculator()

    async def execute(self, request: ToolRequest) -> ToolResult:
        expression = request.text or request.options.get("expression", "")
        try:
            value = self._calculator.evaluate(expression)
        except InvalidRequest as error:
            return ErrorResult(
                code=error.code,
                message="Use arithmetic with numbers, parentheses, and + - * / // % **.",
            )
        return TextResult(
            text=self._format(value),
            title="Calculator",
            input_text=expression.strip(),
            actions=(share_action(),),
        )

    @staticmethod
    def _format(value: int | float) -> str:
        if isinstance(value, float) and value.is_integer():
            return f"{int(value):,}"
        if isinstance(value, int):
            return f"{value:,}"
        return f"{value:,.12g}"
