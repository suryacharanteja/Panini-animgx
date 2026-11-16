# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
"""Bounded mathematical scene data and a small arithmetic expression language."""

from __future__ import annotations

import ast
import math
from collections.abc import Callable
from functools import lru_cache
from typing import cast

MATH_VISUALS = ("equation", "graph", "geometry", "calculus", "vectors")
MATH_REQUIRED = {
    "equation": {"equations"},
    "graph": {"expression", "x_min", "x_max", "y_min", "y_max"},
    "calculus": {"expression", "x_min", "x_max", "y_min", "y_max", "operation"},
    "geometry": {"a", "b"},
    "vectors": {"ax", "ay", "bx", "by"},
}
FUNCTIONS: dict[str, Callable[[float], float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "abs": abs,
}
CONSTANTS = {"pi": math.pi, "e": math.e}

MATH_SCHEMA: dict[str, object] = {
    "type": "object",
    "description": (
        "All values used by the selected tool must be supplied: equation needs "
        "equations; graph needs expression and all four axis bounds; calculus also "
        "needs operation; geometry needs a and b; vectors needs ax, ay, bx and by. "
        "Missing content is rejected, never replaced with an example topic."
    ),
    "properties": {
        "equations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {"type": "string", "minLength": 1, "maxLength": 200},
            "description": "Equation steps in LaTeX, in the order to transform them.",
        },
        "expression": {
            "type": "string",
            "maxLength": 120,
            "description": "Function of x using + - * / ** and sin/cos/tan/sqrt/exp/log/abs; e.g. x**2 or sin(x).",
        },
        "x_min": {"type": "number", "minimum": -20, "maximum": 20},
        "x_max": {"type": "number", "minimum": -20, "maximum": 20},
        "y_min": {"type": "number", "minimum": -20, "maximum": 20},
        "y_max": {"type": "number", "minimum": -20, "maximum": 20},
        "operation": {"type": "string", "enum": ["derivative", "integral"]},
        "a": {"type": "number", "minimum": 0.01, "maximum": 10_000},
        "b": {"type": "number", "minimum": 0.01, "maximum": 10_000},
        "ax": {"type": "number", "minimum": -4, "maximum": 4},
        "ay": {"type": "number", "minimum": -4, "maximum": 4},
        "bx": {"type": "number", "minimum": -4, "maximum": 4},
        "by": {"type": "number", "minimum": -4, "maximum": 4},
    },
    "additionalProperties": False,
}


def _bounded_number(value: object, low: float, high: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low <= value <= high
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a number between {low:g} and {high:g}.")
    return float(value)


@lru_cache(maxsize=128)
def _expression_tree(expression: str) -> ast.expr:
    if not expression.strip() or len(expression) > 120:
        raise ValueError("Function must be nonempty text up to 120 characters.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise ValueError("Use a function such as x**2, sin(x), or 2*x+3.") from error
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("Function is too complex; use a shorter expression.")

    def check(node: ast.expr) -> None:
        if isinstance(node, ast.Constant):
            _bounded_number(node.value, -1e6, 1e6, "Function constant")
        elif isinstance(node, ast.Name):
            if node.id not in ("x", *CONSTANTS):
                raise ValueError("Function names are x, pi, and e.")
        elif isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub)
        ):
            check(node.operand)
        elif isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
        ):
            check(node.left)
            check(node.right)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTIONS
            and len(node.args) == 1
            and not node.keywords
        ):
            check(node.args[0])
        else:
            raise ValueError(
                "Use arithmetic and sin, cos, tan, sqrt, exp, log, or abs only."
            )

    check(tree.body)
    return tree.body


def _calculate(node: ast.expr, x: float) -> float:
    if isinstance(node, ast.Constant):
        value = float(cast(float | int, node.value))
    elif isinstance(node, ast.Name):
        value = x if node.id == "x" else CONSTANTS[node.id]
    elif isinstance(node, ast.UnaryOp):
        value = _calculate(node.operand, x)
        if isinstance(node.op, ast.USub):
            value = -value
    elif isinstance(node, ast.Call):
        value = FUNCTIONS[cast(ast.Name, node.func).id](_calculate(node.args[0], x))
    elif isinstance(node, ast.BinOp):
        left, right = _calculate(node.left, x), _calculate(node.right, x)
        if isinstance(node.op, ast.Add):
            value = left + right
        elif isinstance(node.op, ast.Sub):
            value = left - right
        elif isinstance(node.op, ast.Mult):
            value = left * right
        elif isinstance(node.op, ast.Div):
            value = left / right
        else:
            if abs(right) > 16:
                raise ValueError("Function exponents must be between -16 and 16.")
            if left < 0 and not right.is_integer():
                raise ValueError("Function must be real-valued over its x range.")
            value = math.pow(left, right)
    else:
        raise ValueError("Unsupported function expression.")
    if not math.isfinite(value) or abs(value) > 1e6:
        raise ValueError("Function values must be finite and no larger than 1,000,000.")
    return value


def evaluate_expression(expression: str, x: float) -> float:
    """Evaluate validated arithmetic without executing Python or model-written code.

    Args:
        expression: A bounded function of x in the Studio arithmetic language.
        x: The function's real-valued argument.

    Returns:
        The finite real-valued result.

    Raises:
        ValueError: If the expression is unsupported or undefined at x.
    """
    try:
        return _calculate(_expression_tree(expression), float(x))
    except (OverflowError, ZeroDivisionError) as error:
        raise ValueError(
            "Function is undefined or too large in this x range."
        ) from error


def _latex(node: ast.expr) -> str:
    if isinstance(node, ast.Constant):
        number = str(node.value)
        if "e" in number.lower():
            mantissa, exponent = number.lower().split("e")
            return mantissa + r"\times 10^{" + str(int(exponent)) + "}"
        return number.removesuffix(".0")
    if isinstance(node, ast.Name):
        return r"\pi" if node.id == "pi" else node.id
    if isinstance(node, ast.UnaryOp):
        prefix = "-" if isinstance(node.op, ast.USub) else "+"
        return prefix + r"\left(" + _latex(node.operand) + r"\right)"
    if isinstance(node, ast.Call):
        name = cast(ast.Name, node.func).id
        argument = _latex(node.args[0])
        if name == "sqrt":
            return r"\sqrt{" + argument + "}"
        if name == "abs":
            return r"\left|" + argument + r"\right|"
        return (
            "\\" + ("ln" if name == "log" else name) + r"\left(" + argument + r"\right)"
        )
    if isinstance(node, ast.BinOp):
        left, right = _latex(node.left), _latex(node.right)
        if isinstance(node.op, ast.Div):
            return r"\frac{" + left + "}{" + right + "}"
        if isinstance(node.op, ast.Pow):
            return r"\left(" + left + r"\right)^{" + right + "}"
        symbol = (
            "+"
            if isinstance(node.op, ast.Add)
            else "-"
            if isinstance(node.op, ast.Sub)
            else r"\cdot "
        )
        return r"\left(" + left + symbol + right + r"\right)"
    raise ValueError("Unsupported function expression.")


def expression_latex(expression: str) -> str:
    """Typeset an arithmetic expression as LaTeX while preserving its grouping."""
    return _latex(_expression_tree(expression))


def validate_math(visual: str, value: object = None) -> dict[str, object]:
    """Normalize supplied tool parameters without substituting mathematical content."""
    if visual not in MATH_REQUIRED:
        raise ValueError(f"Unsupported math visual: {visual}.")
    if isinstance(value, dict):
        options = cast(dict[str, object], value)
    else:
        raise ValueError(
            "Math parameters must be an object with the intended tool values."
        )
    missing = MATH_REQUIRED[visual] - options.keys()
    if missing:
        raise ValueError(
            f"Math visual {visual} requires {', '.join(sorted(missing))}; "
            "provide intended values instead of substituting example content."
        )
    if visual == "equation":
        equations = options["equations"]
        if not isinstance(equations, list) or not 1 <= len(equations) <= 6:
            raise ValueError("Use 1 to 6 equation steps in LaTeX.")
        cleaned: list[str] = []
        for equation in equations:
            if (
                not isinstance(equation, str)
                or not equation.strip()
                or len(equation) > 200
                or any(ord(char) < 32 for char in equation)
            ):
                raise ValueError(
                    "Each equation must be LaTeX text up to 200 characters."
                )
            cleaned.append(equation.strip())
        return {"equations": cleaned}
    if visual in ("graph", "calculus"):
        expression = options["expression"]
        if not isinstance(expression, str):
            raise ValueError("Function must be text such as x**2 or sin(x).")
        expression = expression.strip()
        _expression_tree(expression)
        bounds = {
            key: _bounded_number(options[key], -20, 20, key)
            for key in ("x_min", "x_max", "y_min", "y_max")
        }
        if any(
            bounds[f"{axis}_max"] - bounds[f"{axis}_min"] < 0.1
            and not math.isclose(
                bounds[f"{axis}_max"] - bounds[f"{axis}_min"],
                0.1,
                rel_tol=0,
                abs_tol=1e-10,
            )
            for axis in ("x", "y")
        ):
            raise ValueError("Axis maximum must exceed its minimum by at least 0.1.")
        operation = options["operation"] if visual == "calculus" else None
        if visual == "calculus" and operation not in ("derivative", "integral"):
            raise ValueError("Calculus operation must be derivative or integral.")
        if (
            visual == "calculus"
            and operation == "integral"
            and not bounds["y_min"] <= 0 <= bounds["y_max"]
        ):
            raise ValueError("The integral y range must include zero.")
        # Match the renderer's sampling grid so accepted domains also plot there.
        for index in range(401):
            x = bounds["x_min"] + (bounds["x_max"] - bounds["x_min"]) * index / 400
            try:
                y = evaluate_expression(expression, x)
            except ValueError as error:
                raise ValueError(
                    f"Function is invalid near x={x:g}: {error}"
                ) from error
            if (
                visual == "calculus"
                and operation == "integral"
                and not bounds["y_min"] <= y <= bounds["y_max"]
            ):
                raise ValueError("The integral y range must contain the full function.")
        result: dict[str, object] = {"expression": expression, **bounds}
        if visual == "calculus":
            result["operation"] = operation
        return result
    if visual == "geometry":
        return {
            key: _bounded_number(options[key], 0.01, 10_000, key) for key in ("a", "b")
        }
    if visual == "vectors":
        return {
            key: _bounded_number(options[key], -4, 4, key)
            for key in ("ax", "ay", "bx", "by")
        }
    raise ValueError(f"Unsupported math visual: {visual}.")
