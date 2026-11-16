# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
"""Numerical correctness and bounds of Studio's mathematical scene language."""

import math
from copy import deepcopy
from typing import cast

import pytest
from studio import math_spec

_PARAMETERS: dict[str, dict[str, object]] = {
    "equation": {"equations": [r"F=ma"]},
    "graph": {"expression": "x**2", "x_min": -3, "x_max": 3, "y_min": -1, "y_max": 9},
    "calculus": {
        "expression": "x**2",
        "x_min": -3,
        "x_max": 3,
        "y_min": -1,
        "y_max": 9,
        "operation": "derivative",
    },
    "geometry": {"a": 3, "b": 4},
    "vectors": {"ax": 2, "ay": 1, "bx": -1, "by": 2},
}


def _parameters(
    visual: str, overrides: dict[str, object] | None = None
) -> dict[str, object]:
    return {**deepcopy(_PARAMETERS[visual]), **(overrides or {})}


@pytest.mark.parametrize(
    ("expression", "x", "expected"),
    [
        ("2*x+3", 2, 7),
        ("(x+1)*2", 3, 8),
        ("x+1*2", 3, 5),
        ("-x**2", 3, -9),
        ("(-x)**2", 3, 9),
        ("2**-3", 0, 0.125),
        ("1/(x+1)", 3, 0.25),
        ("sin(pi/2)", 0, 1),
        ("cos(pi)", 0, -1),
        ("tan(pi/4)", 0, 1),
        ("sqrt(x)", 9, 3),
        ("log(e)", 0, 1),
        ("exp(0)", 0, 1),
        ("abs(x)", -3, 3),
        ("+x", -2, -2),
    ],
)
def test_arithmetic_and_allowed_functions_are_numerically_correct(
    expression: str, x: float, expected: float
) -> None:
    assert math_spec.evaluate_expression(expression, x) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "x" * 121,
        "+".join(["x"] * 24),
        "x.__class__",
        "x[0]",
        "__import__('os')",
        "[x for x in (1, 2)]",
        "(lambda: 1)()",
        "sin(x=1)",
        "sin(x, 2)",
        "math.sin(x)",
        "sin(*[x])",
        "True",
        "'x'",
        "[x]",
        "x if x else 1",
        "x < 2",
        "x//2",
        "x%2",
        "unknown(x)",
        "y+1",
        "1000001",
        "1e309",
    ],
)
def test_expression_language_rejects_python_features_and_unbounded_input(
    expression: str,
) -> None:
    with pytest.raises(ValueError, match=r"Function|Use"):
        math_spec.evaluate_expression(expression, 2)
    with pytest.raises(ValueError, match=r"Function|Use"):
        math_spec.expression_latex(expression)


@pytest.mark.parametrize(
    ("expression", "x"),
    [
        ("1/x", 0),
        ("sqrt(x)", -1),
        ("log(x)", 0),
        ("exp(x)", 1000),
        ("x**17", 1),
        ("x**-17", 1),
        ("x**0.5", -1),
        ("1000000*x", 2),
        ("x", math.inf),
        ("x", math.nan),
    ],
)
def test_expression_values_are_real_finite_and_bounded(
    expression: str, x: float
) -> None:
    with pytest.raises(ValueError, match=r"Function|math domain|undefined|input"):
        math_spec.evaluate_expression(expression, x)


def test_latex_keeps_grouped_arithmetic_and_uses_math_constructs() -> None:
    assert math_spec.expression_latex("(x+1)*2") == (
        r"\left(\left(x+1\right)\cdot 2\right)"
    )
    assert math_spec.expression_latex("(x+1)**2") == (
        r"\left(\left(x+1\right)\right)^{2}"
    )
    assert math_spec.expression_latex("1/(x+1)") == r"\frac{1}{\left(x+1\right)}"
    assert math_spec.expression_latex("sqrt(abs(x))") == r"\sqrt{\left|x\right|}"
    assert math_spec.expression_latex("sin(pi)") == r"\sin\left(\pi\right)"
    assert math_spec.expression_latex("log(e)") == r"\ln\left(e\right)"


def test_latex_typesets_scientific_numbers_and_keeps_decimal_precision() -> None:
    assert math_spec.expression_latex("1e-6*x") == (
        r"\left(1\times 10^{-6}\cdot x\right)"
    )
    assert math_spec.expression_latex("1.23456789*x") == (
        r"\left(1.23456789\cdot x\right)"
    )


@pytest.mark.parametrize("visual", math_spec.MATH_VISUALS)
def test_explicit_parameters_are_renderable_and_return_fresh_data(visual: str) -> None:
    source = _parameters(visual)
    validated = math_spec.validate_math(visual, source)
    assert math_spec.validate_math(visual, validated) == validated
    validated["unrelated"] = "modified"
    assert "unrelated" not in source
    if visual == "equation":
        equations = validated["equations"]
        assert isinstance(equations, list)
        equations.append("mutated")
        fresh_equations = math_spec.validate_math(visual, source)["equations"]
        assert isinstance(fresh_equations, list)
        assert "mutated" not in fresh_equations


@pytest.mark.parametrize("visual", math_spec.MATH_VISUALS)
def test_absent_math_content_does_not_silently_render_an_example(visual: str) -> None:
    with pytest.raises(ValueError, match="object with the intended tool values"):
        math_spec.validate_math(visual)
    with pytest.raises(ValueError, match="requires"):
        math_spec.validate_math(visual, {})


@pytest.mark.parametrize(
    ("visual", "missing"),
    [(visual, key) for visual, parameters in _PARAMETERS.items() for key in parameters],
)
def test_every_tool_input_is_required(visual: str, missing: str) -> None:
    parameters = _parameters(visual)
    parameters.pop(missing)
    with pytest.raises(ValueError, match=f"requires {missing}"):
        math_spec.validate_math(visual, parameters)


def test_parameters_are_normalized_without_mutating_or_retaining_unused_fields() -> (
    None
):
    source: dict[str, object] = {"equations": ["  x=2  "], "expression": "ignored"}
    assert math_spec.validate_math("equation", source) == {"equations": ["x=2"]}
    assert source == {"equations": ["  x=2  "], "expression": "ignored"}
    assert math_spec.validate_math("geometry", {"a": 5, "b": 12, "code": "x"}) == {
        "a": 5.0,
        "b": 12.0,
    }


@pytest.mark.parametrize(
    ("a", "b"),
    [(5, 12), (0.01, 0.02), (30, 4000), (10_000, 0.01), (10_000, 10_000)],
)
def test_geometry_preserves_authored_small_and_large_side_lengths(
    a: float, b: float
) -> None:
    assert math_spec.validate_math("geometry", {"a": a, "b": b}) == {"a": a, "b": b}


def test_geometry_generation_schema_and_runtime_accept_the_same_endpoints() -> None:
    properties = cast(dict[str, object], math_spec.MATH_SCHEMA["properties"])
    for leg in ("a", "b"):
        bounds = cast(dict[str, object], properties[leg])
        assert bounds["minimum"] == 0.01
        assert bounds["maximum"] == 10_000
        for endpoint in (bounds["minimum"], bounds["maximum"]):
            assert (
                math_spec.validate_math(
                    "geometry", _parameters("geometry", {leg: endpoint})
                )[leg]
                == endpoint
            )


@pytest.mark.parametrize(
    "equations",
    [[], ["x=2"] * 7, [""], ["x" * 201], ["x\n=2"], [123], "x=2"],
)
def test_equation_steps_have_bounded_count_and_text(equations: object) -> None:
    with pytest.raises(ValueError, match="equation"):
        math_spec.validate_math("equation", {"equations": equations})


@pytest.mark.parametrize("value", [True, "3", None, math.nan, math.inf, 10**1000])
def test_numeric_parameters_reject_non_numbers_and_extreme_values(
    value: object,
) -> None:
    for visual, key in (("geometry", "a"), ("vectors", "ax"), ("graph", "x_max")):
        with pytest.raises(ValueError, match=key):
            math_spec.validate_math(visual, _parameters(visual, {key: value}))


@pytest.mark.parametrize(
    ("visual", "parameters"),
    [
        ("geometry", {"a": 0.0099}),
        ("geometry", {"a": 0}),
        ("geometry", {"b": -1}),
        ("geometry", {"b": 10_000.01}),
        ("vectors", {"ax": -4.01}),
        ("vectors", {"by": 4.01}),
        ("graph", {"x_min": -20.01}),
        ("graph", {"y_max": 20.01}),
        ("graph", {"x_min": 3, "x_max": 3}),
        ("graph", {"x_min": 3, "x_max": 2}),
        ("graph", {"y_min": 0, "y_max": 0.01}),
        ("graph", {"expression": "log(x)"}),
        ("graph", {"expression": "sqrt(x)"}),
        ("graph", {"expression": "1/x"}),
        ("graph", {"expression": "x**17"}),
        ("graph", {"expression": "exp(1000)"}),
        ("calculus", {"operation": "other"}),
        ("calculus", {"operation": "integral", "y_min": 1}),
        ("calculus", {"operation": "integral", "y_max": 2}),
    ],
)
def test_scene_parameters_reject_invalid_dimensions_and_domains(
    visual: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match=r"must|Axis|Function|operation|range"):
        math_spec.validate_math(visual, _parameters(visual, parameters))


def test_integral_accepts_a_contained_function_and_positive_log_domain() -> None:
    integral = math_spec.validate_math(
        "calculus",
        _parameters(
            "calculus",
            {"expression": "x**2", "operation": "integral", "y_min": 0, "y_max": 9},
        ),
    )
    assert integral["operation"] == "integral"
    assert integral["y_min"] == 0
    logarithm = math_spec.validate_math(
        "graph",
        _parameters(
            "graph", {"expression": "log(x)", "x_min": 0.1, "x_max": 5, "y_min": -3}
        ),
    )
    assert logarithm["expression"] == "log(x)"


@pytest.mark.parametrize("axis", ["x", "y"])
def test_decimal_axis_gap_accepts_point_one_without_accepting_smaller_gaps(
    axis: str,
) -> None:
    minimum, maximum = f"{axis}_min", f"{axis}_max"
    normalized = math_spec.validate_math(
        "graph", _parameters("graph", {minimum: 0.2, maximum: 0.3})
    )
    assert normalized[minimum] == 0.2
    assert normalized[maximum] == 0.3
    with pytest.raises(ValueError, match="Axis maximum"):
        math_spec.validate_math(
            "graph", _parameters("graph", {minimum: 0.2, maximum: 0.2999})
        )


def test_graph_rejects_a_shifted_singularity_on_the_renderer_sample_grid() -> None:
    with pytest.raises(ValueError, match=r"Function is invalid near x=0\.15"):
        math_spec.validate_math(
            "graph", _parameters("graph", {"expression": "1/(x-0.15)"})
        )


@pytest.mark.parametrize("value", [[], "parameters", 3, True])
def test_math_parameters_must_be_an_object(value: object) -> None:
    with pytest.raises(ValueError, match="object"):
        math_spec.validate_math("equation", value)
