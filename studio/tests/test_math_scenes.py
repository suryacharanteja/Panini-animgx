# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT

"""Mathematical correctness, visible bounds and storyboard render integration."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from studio import math_scenes, renderer

import manimgx as m


def _area(points: np.ndarray) -> float:
    return (
        abs(
            float(
                np.dot(points[:, 0], np.roll(points[:, 1], -1))
                - np.dot(points[:, 1], np.roll(points[:, 0], -1))
            )
        )
        / 2
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, "5"),
        (12, "12"),
        (0.01, "0.01"),
        (0.0001, "0.0001"),
        (2e8, r"2\times10^{8}"),
        (1.2345e8, r"1.2345\times10^{8}"),
        (1e-6, r"1\times10^{-6}"),
        (-1.5e-6, r"-1.5\times10^{-6}"),
    ],
)
def test_numeric_math_labels_preserve_ordinary_values_and_typeset_exponents(
    value: float, expected: str
) -> None:
    assert math_scenes._number_latex(value) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (5, 12, r"5^2+12^2=169\quad(c=\sqrt{169})"),
        (0.01, 0.02, r"0.01^2+0.02^2=0.0005\quad(c=\sqrt{0.0005})"),
        (
            10_000,
            10_000,
            r"10000^2+10000^2=2\times10^{8}\quad(c=\sqrt{2\times10^{8}})",
        ),
        (
            1e-6,
            2e-6,
            r"\left(1\times10^{-6}\right)^2+\left(2\times10^{-6}\right)^2"
            r"=5\times10^{-12}\quad(c=\sqrt{5\times10^{-12}})",
        ),
    ],
)
def test_geometry_numeric_formula_groups_scientific_legs_and_uses_actual_squared_sum(
    a: float, b: float, expected: str
) -> None:
    assert math_scenes._geometry_values_latex(a, b) == expected


def test_large_geometry_uses_correct_scientific_notation_in_native_mathtex() -> None:
    scene = m.Scene()
    result = math_scenes.animate_math(
        scene, "geometry", {"a": 10_000, "b": 10_000}, "#8DABFF", "#FFFFFF", 2.05
    )
    values = result[-1]
    assert isinstance(values, m.MathTex)
    assert "".join(values.tex_strings) == (
        r"10000^2+10000^2=2\times10^{8}\quad(c=\sqrt{2\times10^{8}})"
    )
    assert values.width <= 10.7
    assert values.height <= 0.321
    assert scene.time == pytest.approx(2.05)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (3, 4),
        (5, 12),
        (0.01, 0.02),
        (3000, 4000),
        (10_000, 0.01),
        (0.01, 10_000),
        (10_000, 10_000),
        (0.5, 10),
        (10, 0.5),
        (10, 10),
    ],
)
def test_pythagorean_squares_have_correct_side_lengths_and_areas(
    a: float, b: float
) -> None:
    triangle, squares = math_scenes._triangle_points(a, b)
    assert np.linalg.norm(triangle[1] - triangle[0]) == pytest.approx(a)
    assert np.linalg.norm(triangle[2] - triangle[0]) == pytest.approx(b)
    assert np.dot(triangle[1] - triangle[0], triangle[2] - triangle[0]) == 0
    assert np.linalg.norm(triangle[2] - triangle[1]) == pytest.approx(np.hypot(a, b))
    assert [_area(square) for square in squares] == pytest.approx(
        [a * a, b * b, a * a + b * b]
    )
    for square in squares:
        sides = np.roll(square, -1, axis=0) - square
        assert np.linalg.norm(sides, axis=1) == pytest.approx(
            [np.linalg.norm(sides[0])] * 4
        )
        assert np.dot(sides[0], sides[1]) / (
            np.linalg.norm(sides[0]) * np.linalg.norm(sides[1])
        ) == pytest.approx(0, abs=1e-12)


@pytest.mark.parametrize("x", [-2.0, 0.0, 1.5, 3.0])
def test_derivative_is_in_function_coordinates(x: float) -> None:
    assert math_scenes._derivative("x**2", x, -3, 3) == pytest.approx(2 * x, abs=0.0004)


def test_derivative_rejects_a_cusp_instead_of_showing_zero_slope() -> None:
    with pytest.raises(ValueError, match=r"Derivative is undefined near x=0.*smooth"):
        math_scenes._derivative("abs(x)", 0, -3, 3)


@pytest.mark.parametrize("x", [-3, -1.5, 0, 1.5, 3])
def test_smooth_sine_derivative_and_endpoint_stencils_remain_supported(
    x: float,
) -> None:
    assert math_scenes._derivative("sin(x)", x, -3, 3) == pytest.approx(
        np.cos(x), abs=0.0003
    )


@pytest.mark.parametrize(("x", "slope"), [(-1.5, -3), (0, 0), (1.5, 3), (1, 1000)])
def test_tangent_endpoints_stay_in_plot_and_preserve_mathematical_slope(
    x: float, slope: float
) -> None:
    endpoints = math_scenes._tangent_endpoints(x, x * x, slope, (-3, 3, -1, 9))
    for px, py in endpoints:
        assert -3 <= px <= 3
        assert -1 - 1e-9 <= py <= 9 + 1e-9
        assert py == pytest.approx(x * x + slope * (px - x))
    assert endpoints[0][0] < endpoints[1][0]


def test_graph_clips_true_curve_at_visible_bounds_without_flattening() -> None:
    assert np.array(
        math_scenes._visible_intervals("x**2", (-3, 3, -1, 4))
    ) == pytest.approx(np.array([[-2, 2]]))
    intervals = math_scenes._visible_intervals("x**2", (-3, 3, 1, 4))
    assert np.array(intervals) == pytest.approx(np.array([[-2, -1], [1, 2]]), abs=1e-7)
    plot = math_scenes._plot(
        {"expression": "x**2", "x_min": -3, "x_max": 3, "y_min": -1, "y_max": 4},
        "#8DABFF",
        "#FFFFFF",
    )
    curve = plot.curves[0]
    assert isinstance(curve, m.ParametricFunction)
    assert curve.function(1.5) == pytest.approx(plot.axes.c2p(1.5, 2.25))
    assert curve.function(0) == pytest.approx(plot.axes.c2p(0, 0))
    assert curve.t_min == pytest.approx(-2)
    assert curve.t_max == pytest.approx(2)


def test_graph_reports_when_function_is_outside_visible_bounds() -> None:
    with pytest.raises(ValueError, match="outside"):
        math_scenes._plot(
            {"expression": "20", "x_min": -3, "x_max": 3, "y_min": -1, "y_max": 9},
            "#8DABFF",
            "#FFFFFF",
        )


@pytest.mark.parametrize("expression", ["tan(x)", "1/(x-0.151)"])
def test_graph_does_not_connect_opposite_sides_of_a_pole(expression: str) -> None:
    intervals = math_scenes._visible_intervals(expression, (-3, 3, -4, 4))
    assert intervals
    poles = [-np.pi / 2, np.pi / 2] if expression == "tan(x)" else [0.151]
    for left, right in intervals:
        assert right - left > 1e-7
        assert not any(left <= pole <= right for pole in poles)


@pytest.mark.parametrize("formula", [r"\frac{x+1}{2}=3", r"x^2+2x+1=0"])
def test_equation_matching_preserves_complete_latex_groups(formula: str) -> None:
    formatted = math_scenes._formula(formula, "#FFFFFF")
    assert isinstance(formatted, m.MathTex)
    assert "=" in formatted.tex_strings
    if r"\frac" in formula:
        assert formatted.tex_strings[0] == r"\frac{x+1}{2}"


@pytest.mark.parametrize(
    ("visual", "options"),
    [
        ("equation", {"equations": [r"2x+3=7", r"2x=4", r"x=2"]}),
        (
            "graph",
            {
                "expression": "sin(x)",
                "x_min": -3,
                "x_max": 3,
                "y_min": -1.5,
                "y_max": 1.5,
            },
        ),
        ("geometry", {"a": 3, "b": 4}),
        ("geometry", {"a": 5, "b": 12}),
        ("geometry", {"a": 0.01, "b": 0.02}),
        ("geometry", {"a": 3000, "b": 4000}),
        ("geometry", {"a": 10_000, "b": 0.01}),
        ("geometry", {"a": 0.01, "b": 10_000}),
        ("geometry", {"a": 10_000, "b": 10_000}),
        ("geometry", {"a": 0.5, "b": 10}),
        ("geometry", {"a": 10, "b": 0.5}),
        (
            "calculus",
            {
                "expression": "x**2",
                "operation": "derivative",
                "x_min": -3,
                "x_max": 3,
                "y_min": -1,
                "y_max": 9,
            },
        ),
        (
            "calculus",
            {
                "expression": "x**2",
                "x_min": 0,
                "x_max": 2,
                "y_min": 0,
                "y_max": 4,
                "operation": "integral",
            },
        ),
        ("vectors", {"ax": 2, "ay": 1, "bx": 1, "by": 2}),
        ("vectors", {"ax": 4, "ay": 4, "bx": 4, "by": 4}),
        ("vectors", {"ax": -4, "ay": -4, "bx": -4, "by": -4}),
        ("vectors", {"ax": 0, "ay": 0, "bx": 0, "by": 0}),
        ("vectors", {"ax": 4, "ay": 4, "bx": -4, "by": -4}),
    ],
)
def test_real_math_animations_fit_title_and_caption_space_with_exact_timing(
    visual: str, options: dict[str, object]
) -> None:
    scene = m.Scene()
    result = math_scenes.animate_math(
        scene, visual, options, "#8DABFF", "#FFFFFF", 2.05
    )
    assert scene.time == pytest.approx(2.05)
    assert result.get_top()[1] <= 2.4
    assert result.get_bottom()[1] >= -2.5
    assert result.width <= 11
    assert all(np.isfinite(obj.points).all() for obj in result.get_family())


def test_integral_shows_both_signs_when_signed_total_is_zero() -> None:
    scene = m.Scene()
    result = math_scenes.animate_math(
        scene,
        "calculus",
        {
            "expression": "x",
            "x_min": -1,
            "x_max": 1,
            "y_min": -1,
            "y_max": 1,
            "operation": "integral",
        },
        "#8DABFF",
        "#FFFFFF",
        2.05,
    )
    areas = result[1]
    negative, positive = areas[0], areas[1]
    label = result[-1]
    assert isinstance(negative, m.Polygon)
    assert isinstance(positive, m.Polygon)
    assert isinstance(label, m.MathTex)
    assert len(areas) == 2
    assert areas[0].fill_color != areas[1].fill_color
    assert "0.000" in label.tex_string
    assert _area(negative.get_vertices()) == pytest.approx(
        _area(positive.get_vertices()), rel=0.001
    )


def test_vector_arrows_use_equal_coordinate_scales_and_head_to_tail_sum() -> None:
    scene = m.Scene()
    result = math_scenes.animate_math(
        scene,
        "vectors",
        {"ax": 2, "ay": 1, "bx": 1, "by": 2},
        "#8DABFF",
        "#FFFFFF",
        2.05,
    )
    plane, a_arrow, b_arrow, sum_arrow = result[0], result[4], result[5], result[6]
    assert isinstance(plane, m.NumberPlane)
    assert np.linalg.norm(plane.c2p(1, 0) - plane.c2p(0, 0)) == pytest.approx(
        np.linalg.norm(plane.c2p(0, 1) - plane.c2p(0, 0))
    )
    assert a_arrow.get_end() == pytest.approx(plane.c2p(2, 1))
    assert b_arrow.get_start() == pytest.approx(a_arrow.get_end())
    assert b_arrow.get_end() == pytest.approx(plane.c2p(3, 3))
    assert sum_arrow.get_end() == pytest.approx(b_arrow.get_end())


def test_renderer_dispatches_reviewed_math_and_restores_config_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = (m.config.pixel_width, m.config.pixel_height, m.config.frame_rate)
    plan: dict[str, object] = {
        "title": "Core math",
        "mode": "math",
        "scenes": [
            {
                "title": "Custom equation",
                "narration": "Explain a fraction",
                "visual": "equation",
                "math": {"equations": [r"\frac{x+1}{2}=3", "x=5"]},
                "duration": 3,
                "background": "#162033",
                "accent": "#8DABFF",
            }
        ],
    }

    def render(scene: m.Scene, path: Path, *, preset: str, crf: float) -> None:
        scene.construct()
        assert scene.time == pytest.approx(3)
        assert (m.config.pixel_width, m.config.pixel_height, m.config.frame_rate) == (
            960,
            540,
            24,
        )
        assert not scene.mobjects
        path.write_bytes(b"rendered")

    monkeypatch.setattr(m.Scene, "render", render)
    shots = renderer._prepare_shots(plan, tmp_path, {}, lambda _message: None)
    assert shots[0].math == {"equations": [r"\frac{x+1}{2}=3", "x=5"]}
    target = renderer.render_project(plan, tmp_path, {}, lambda _message: None)
    assert target.read_bytes() == b"rendered"
    assert (
        m.config.pixel_width,
        m.config.pixel_height,
        m.config.frame_rate,
    ) == original
