# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT

"""Mathematical animations built from ManimGX's authoring primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np

from studio.math_spec import evaluate_expression, expression_latex

if TYPE_CHECKING:
    import manimgx as m


def _number(options: dict[str, object], key: str) -> float:
    return float(cast(float, options[key]))


def _number_latex(value: float) -> str:
    """Keep ordinary numeric labels and typeset exponent notation as mathematics."""
    formatted = f"{value:g}"
    if "e" not in formatted.lower():
        return formatted
    mantissa, exponent = formatted.lower().split("e")
    return rf"{mantissa}\times10^{{{int(exponent)}}}"


def _geometry_values_latex(a: float, b: float) -> str:
    def squared(value: float) -> str:
        number = _number_latex(value)
        if r"\times" in number:
            number = rf"\left({number}\right)"
        return number + "^2"

    sum_of_squares = _number_latex(a * a + b * b)
    return (
        rf"{squared(a)}+{squared(b)}={sum_of_squares}"
        rf"\quad(c=\sqrt{{{sum_of_squares}}})"
    )


def _equation_parts(formula: str) -> list[str]:
    """Keep complete LaTeX groups intact while isolating top-level math terms."""
    parts: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(formula):
        if index > 0 and formula[index - 1] == "\\":
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        elif depth == 0 and character in "=+":
            if formula[start:index].strip():
                parts.append(formula[start:index].strip())
            parts.append(character)
            start = index + 1
    if formula[start:].strip():
        parts.append(formula[start:].strip())
    return parts or [formula]


def _formula(formula: str, color: str, *, size: float = 44) -> m.MathTex:
    import manimgx as m

    result = m.MathTex(*_equation_parts(formula), font_size=size, color=color)
    if result.width > 10.7:
        result.scale_to_fit_width(10.7)
    if result.height > 1.65:
        result.scale_to_fit_height(1.65)
    return result


def _triangle_points(a: float, b: float) -> tuple[np.ndarray, list[np.ndarray]]:
    """Return a right triangle and outward squares whose areas are a², b², c²."""
    triangle = np.array([[0, 0, 0], [a, 0, 0], [0, b, 0]], dtype=float)
    squares = [
        np.array([[0, 0, 0], [a, 0, 0], [a, -a, 0], [0, -a, 0]], dtype=float),
        np.array([[0, 0, 0], [0, b, 0], [-b, b, 0], [-b, 0, 0]], dtype=float),
        np.array([[a, 0, 0], [0, b, 0], [b, a + b, 0], [a + b, a, 0]]),
    ]
    return triangle, squares


def _derivative(expression: str, x: float, low: float, high: float) -> float:
    """Estimate the derivative in data coordinates, with one-sided endpoint stencils."""
    step = min(1e-4 * max(1, abs(x)), (high - low) / 1000)
    left, right = max(low, x - step), min(high, x + step)
    y_left = evaluate_expression(expression, left)
    y_right = evaluate_expression(expression, right)
    if left < x < right:
        y = evaluate_expression(expression, x)
        left_slope = (y - y_left) / (x - left)
        right_slope = (y_right - y) / (right - x)
        mismatch = abs(left_slope - right_slope)
        tolerance = max(1e-6, 4 * step * max(1, abs(left_slope), abs(right_slope)))
        if mismatch > tolerance:
            left_half, right_half = (left + x) / 2, (x + right) / 2
            half_left_slope = (y - evaluate_expression(expression, left_half)) / (
                x - left_half
            )
            half_right_slope = (evaluate_expression(expression, right_half) - y) / (
                right_half - x
            )
            # Smooth curvature's mismatch shrinks with the stencil. A cusp keeps
            # distinct left and right derivatives even as the stencil contracts.
            if abs(half_left_slope - half_right_slope) >= mismatch * 0.75:
                raise ValueError(
                    f"Derivative is undefined near x={x:g}; choose a smooth function/range."
                )
    return (y_right - y_left) / (right - left)


def _tangent_endpoints(
    x: float,
    y: float,
    slope: float,
    bounds: tuple[float, float, float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Clip the true tangent line to the graph's visible data rectangle."""
    x_min, x_max, y_min, y_max = bounds
    left, right = x_min, x_max
    if abs(slope) > 1e-12:
        crossings = sorted((x + (y_min - y) / slope, x + (y_max - y) / slope))
        left, right = max(left, crossings[0]), min(right, crossings[1])
    return (left, y + slope * (left - x)), (right, y + slope * (right - x))


def _visible_intervals(
    expression: str, bounds: tuple[float, float, float, float]
) -> list[tuple[float, float]]:
    """Find visible intervals without distorting function values to fit the plot."""
    x_min, x_max, y_min, y_max = bounds
    xs = np.linspace(x_min, x_max, 401)
    ys = [evaluate_expression(expression, float(x)) for x in xs]
    intervals: list[tuple[float, float]] = []
    current: float | None = x_min if y_min <= ys[0] <= y_max else None

    def crossing(left: float, right: float, boundary: float) -> float | None:
        below = evaluate_expression(expression, left) < boundary
        for _ in range(40):
            middle = (left + right) / 2
            try:
                value = evaluate_expression(expression, middle)
            except ValueError:
                return None
            if (value < boundary) == below:
                left = middle
            else:
                right = middle
        root = (left + right) / 2
        try:
            residual = evaluate_expression(expression, root) - boundary
        except ValueError:
            return None
        # A change of sign at a pole is not an intersection with the plot boundary.
        return root if abs(residual) <= 1e-5 else None

    for index in range(1, len(xs)):
        before, after = ys[index - 1], ys[index]
        left, right = float(xs[index - 1]), float(xs[index])
        was_visible, visible = y_min <= before <= y_max, y_min <= after <= y_max
        if not was_visible and visible:
            current = crossing(left, right, y_min if before < y_min else y_max)
        elif was_visible and not visible and current is not None:
            end = crossing(left, right, y_min if after < y_min else y_max)
            if end is not None and end - current > 1e-7:
                intervals.append((current, end))
            current = None
        elif not was_visible and not visible and (before < y_min) != (after < y_min):
            boundaries = (y_min, y_max) if before < y_min else (y_max, y_min)
            start, end = (crossing(left, right, bound) for bound in boundaries)
            if start is not None and end is not None and end - start > 1e-7:
                intervals.append((start, end))
    if current is not None and x_max - current > 1e-7:
        intervals.append((current, x_max))
    return intervals


def _tick_step(span: float) -> float:
    candidate = span / 5
    base = 10 ** math.floor(math.log10(candidate))
    return next(factor * base for factor in (1, 2, 5, 10) if factor * base >= candidate)


@dataclass(frozen=True)
class _Plot:
    axes: m.Axes
    curves: m.VGroup
    label: m.MathTex
    expression: str
    bounds: tuple[float, float, float, float]
    intervals: list[tuple[float, float]]


def _plot(options: dict[str, object], accent: str, foreground: str) -> _Plot:
    import manimgx as m

    expression = cast(str, options["expression"])
    bounds = (
        _number(options, "x_min"),
        _number(options, "x_max"),
        _number(options, "y_min"),
        _number(options, "y_max"),
    )
    x_min, x_max, y_min, y_max = bounds
    axes = m.Axes(
        x_range=[x_min, x_max, _tick_step(x_max - x_min)],
        y_range=[y_min, y_max, _tick_step(y_max - y_min)],
        x_length=9.0,
        y_length=3.15,
        axis_config={"color": foreground, "include_numbers": True, "font_size": 20},
        tips=False,
    )
    if axes.height > 3.65:
        axes.scale_to_fit_height(3.65)
    axes.move_to([0, -0.25, 0])
    intervals = _visible_intervals(expression, bounds)
    if not intervals:
        raise ValueError("The selected function is outside the visible graph bounds.")
    curves = m.VGroup(
        *(
            axes.plot(
                lambda x: evaluate_expression(expression, x),
                x_range=[left, right, (right - left) / 200],
                color=accent,
                stroke_width=4,
                use_smoothing=False,
            )
            for left, right in intervals
        )
    )
    label = _formula(r"f(x)=" + expression_latex(expression), foreground, size=34)
    if label.height > 0.55:
        label.scale_to_fit_height(0.55)
    label.move_to([0, 2.13, 0])
    return _Plot(axes, curves, label, expression, bounds, intervals)


def _animate_equation(
    scene: m.Scene,
    options: dict[str, object],
    accent: str,
    foreground: str,
    duration: float,
) -> m.VGroup:
    import manimgx as m

    equations = cast(list[str], options["equations"])
    step_duration = duration / len(equations)
    current = _formula(equations[0], accent, size=72).move_to([0, 0.3, 0])
    counter = m.Text(
        f"Step 1 / {len(equations)}", font_size=24, color=foreground
    ).move_to([0, -1.3, 0])
    scene.play(m.Write(current), m.FadeIn(counter), run_time=step_duration * 0.6)
    scene.wait(step_duration * 0.4)
    for index, equation in enumerate(equations[1:], start=2):
        target = _formula(equation, accent, size=72).move_to([0, 0.3, 0])
        target_counter = m.Text(
            f"Step {index} / {len(equations)}", font_size=24, color=foreground
        ).move_to([0, -1.3, 0])
        scene.play(
            m.TransformMatchingTex(current, target, path_arc=0.2),
            m.Transform(counter, target_counter),
            run_time=step_duration * 0.6,
        )
        current = target
        scene.wait(step_duration * 0.4)
    return m.VGroup(current, counter)


def _animate_geometry(
    scene: m.Scene,
    options: dict[str, object],
    accent: str,
    foreground: str,
    duration: float,
) -> m.VGroup:
    import manimgx as m

    a, b = _number(options, "a"), _number(options, "b")
    triangle_points, square_points = _triangle_points(a, b)
    colors = (accent, "#56C8AF", "#EDAA62")
    triangle = m.Polygon(
        *triangle_points, color=foreground, fill_color=foreground, fill_opacity=0.08
    )
    squares = m.VGroup(
        *(
            m.Polygon(*points, color=color, fill_opacity=0.2, stroke_width=2)
            for points, color in zip(square_points, colors, strict=True)
        )
    )
    figure = m.VGroup(triangle, squares)
    figure.scale(min(8.8 / figure.width, 3.35 / figure.height)).move_to([0, 0.15, 0])
    labels = m.VGroup()
    for square, text, color in zip(squares, ("a^2", "b^2", "c^2"), colors, strict=True):
        label = _formula(text, color, size=32)
        label.scale(
            min(
                1,
                0.55 * square.width / label.width,
                0.55 * square.height / label.height,
            )
        )
        label.move_to(square.get_center())
        labels.add(label)
    origin, horizontal, vertical = triangle.get_vertices()
    corner_size = (
        min(np.linalg.norm(horizontal - origin), np.linalg.norm(vertical - origin))
        * 0.16
    )
    right_angle = m.VMobject(color=foreground, stroke_width=2).set_points_as_corners(
        [
            origin + [corner_size, 0, 0],
            origin + [corner_size, corner_size, 0],
            origin + [0, corner_size, 0],
        ]
    )
    law = _formula(r"a^2+b^2=c^2", foreground, size=38).move_to([0, -1.95, 0])
    values = _formula(
        _geometry_values_latex(a, b),
        foreground,
        size=26,
    )
    if values.height > 0.32:
        values.scale_to_fit_height(0.32)
    values.move_to([0, -2.3, 0])
    scene.play(m.Create(triangle), m.Create(right_angle), run_time=duration * 0.2)
    scene.play(m.Create(squares), m.Write(labels), run_time=duration * 0.32)
    scene.play(m.Write(law), m.Write(values), run_time=duration * 0.22)
    scene.wait(duration * 0.26)
    return m.VGroup(figure, right_angle, labels, law, values)


def _animate_graph(
    scene: m.Scene,
    options: dict[str, object],
    accent: str,
    foreground: str,
    duration: float,
) -> m.VGroup:
    import manimgx as m

    plot = _plot(options, accent, foreground)
    left, right = max(plot.intervals, key=lambda pair: pair[1] - pair[0])
    dot = m.Dot(
        plot.axes.c2p(left, evaluate_expression(plot.expression, left)),
        radius=0.075,
        color=foreground,
    )
    trace = m.TracedPath(dot.get_center, stroke_color=foreground, stroke_width=2)
    scene.play(m.Create(plot.axes), m.Write(plot.label), run_time=duration * 0.22)
    scene.play(m.Create(plot.curves), run_time=duration * 0.25)
    scene.add(trace, dot)

    def follow(point: m.Dot, alpha: float) -> None:
        x = left + alpha * (right - left)
        point.move_to(plot.axes.c2p(x, evaluate_expression(plot.expression, x)))

    scene.play(
        m.UpdateFromAlphaFunc(dot, follow), run_time=duration * 0.4, rate_func=m.linear
    )
    trace.clear_updaters()
    scene.wait(duration * 0.13)
    return m.VGroup(plot.axes, plot.curves, plot.label, trace, dot)


def _animate_calculus(
    scene: m.Scene,
    options: dict[str, object],
    accent: str,
    foreground: str,
    duration: float,
) -> m.VGroup:
    import manimgx as m

    plot = _plot(options, accent, foreground)
    scene.play(m.Create(plot.axes), m.Write(plot.label), run_time=duration * 0.2)
    scene.play(m.Create(plot.curves), run_time=duration * 0.2)
    x_min, x_max, y_min, y_max = plot.bounds
    if options["operation"] == "integral":
        xs = np.linspace(x_min, x_max, 801)
        ys = np.array([evaluate_expression(plot.expression, float(x)) for x in xs])
        if y_min > 0 or y_max < 0 or ys.min() < y_min or ys.max() > y_max:
            raise ValueError(
                "Integral bounds must show the x-axis and the complete function."
            )
        integral = float(np.trapezoid(ys, xs))
        # Split at zeros so positive and negative area stay distinct, including
        # functions whose total signed integral is zero.
        areas = m.VGroup()
        start = 0
        for index in range(1, len(xs)):
            if (ys[index] < 0) != (ys[index - 1] < 0) or index == len(xs) - 1:
                points = [plot.axes.c2p(float(xs[start]), 0)]
                points.extend(
                    plot.axes.c2p(float(x), float(y))
                    for x, y in zip(
                        xs[start : index + 1], ys[start : index + 1], strict=True
                    )
                )
                points.append(plot.axes.c2p(float(xs[index]), 0))
                areas.add(
                    m.Polygon(
                        *points,
                        fill_color=accent
                        if ys[start : index + 1].mean() >= 0
                        else foreground,
                        fill_opacity=0.25,
                        stroke_width=0,
                    )
                )
                start = index
        label = _formula(
            rf"\int_{{{x_min:g}}}^{{{x_max:g}}} f(x)\,dx\approx {integral:.3f}",
            foreground,
            size=30,
        )
        if label.height > 0.4:
            label.scale_to_fit_height(0.4)
        label.move_to([0, -2.25, 0])
        scene.play(m.FadeIn(areas), m.Write(label), run_time=duration * 0.35)
        scene.wait(duration * 0.25)
        return m.VGroup(plot.axes, areas, plot.curves, plot.label, label)
    left, right = max(plot.intervals, key=lambda pair: pair[1] - pair[0])
    left, right = left + (right - left) * 0.12, right - (right - left) * 0.12
    x = left
    y = evaluate_expression(plot.expression, x)
    slope = _derivative(plot.expression, x, x_min, x_max)
    ends = _tangent_endpoints(x, y, slope, plot.bounds)
    tangent = m.Line(
        plot.axes.c2p(*ends[0]),
        plot.axes.c2p(*ends[1]),
        color=foreground,
        stroke_width=3,
    )
    dot = m.Dot(plot.axes.c2p(x, y), radius=0.07, color=foreground)
    definition = _formula(r"f'(x)=\lim_{h\to0}\frac{f(x+h)-f(x)}h", foreground, size=29)
    if definition.height > 0.4:
        definition.scale_to_fit_height(0.4)
    definition.move_to([0, -2.25, 0])
    readout_label = m.Text(
        "x =             slope ≈", font_size=21, color=foreground
    ).move_to([2.7, 1.65, 0])
    x_value = m.DecimalNumber(
        x, num_decimal_places=2, font_size=21, color=foreground
    ).move_to([2.15, 1.65, 0])
    slope_value = m.DecimalNumber(
        slope, num_decimal_places=2, font_size=21, color=foreground
    ).move_to([4.25, 1.65, 0])
    moving = m.VGroup(tangent, dot, x_value, slope_value)
    scene.play(
        m.FadeIn(moving),
        m.Write(definition),
        m.FadeIn(readout_label),
        run_time=duration * 0.12,
    )

    def follow(objects: m.VGroup, alpha: float) -> None:
        x = left + alpha * (right - left)
        y = evaluate_expression(plot.expression, x)
        slope = _derivative(plot.expression, x, x_min, x_max)
        ends = _tangent_endpoints(x, y, slope, plot.bounds)
        cast(m.Line, objects[0]).put_start_and_end_on(
            *(plot.axes.c2p(*point) for point in ends)
        )
        objects[1].move_to(plot.axes.c2p(x, y))
        cast(m.DecimalNumber, objects[2]).set_value(x).move_to([2.15, 1.65, 0])
        cast(m.DecimalNumber, objects[3]).set_value(slope).move_to([4.25, 1.65, 0])

    scene.play(
        m.UpdateFromAlphaFunc(moving, follow),
        run_time=duration * 0.38,
        rate_func=m.linear,
    )
    scene.wait(duration * 0.1)
    return m.VGroup(
        plot.axes, plot.curves, plot.label, moving, definition, readout_label
    )


def _animate_vectors(
    scene: m.Scene,
    options: dict[str, object],
    accent: str,
    foreground: str,
    duration: float,
) -> m.VGroup:
    import manimgx as m

    ax, ay = _number(options, "ax"), _number(options, "ay")
    bx, by = _number(options, "bx"), _number(options, "by")
    x_bound = max(2, math.ceil(max(abs(ax), abs(bx), abs(ax + bx))) + 1)
    y_bound = max(2, math.ceil(max(abs(ay), abs(by), abs(ay + by))) + 1)
    unit = min(4.3 / x_bound, 1.65 / y_bound)
    plane = m.NumberPlane(
        x_range=[-x_bound, x_bound, 1],
        y_range=[-y_bound, y_bound, 1],
        x_length=2 * x_bound * unit,
        y_length=2 * y_bound * unit,
        axis_config={"color": foreground},
        background_line_style={
            "stroke_color": foreground,
            "stroke_opacity": 0.2,
            "stroke_width": 1,
        },
    ).move_to([0, -0.1, 0])
    origin, a, b, result = (
        plane.c2p(*point) for point in ((0, 0), (ax, ay), (bx, by), (ax + bx, ay + by))
    )

    def arrow(start: np.ndarray, end: np.ndarray, color: str) -> m.VMobject:
        if np.linalg.norm(end - start) < 1e-9:
            return m.Dot(start, radius=0.055, color=color)
        return m.Arrow(start, end, buff=0, color=color, stroke_width=4, tip_length=0.16)

    a_arrow, b_arrow = arrow(origin, a, accent), arrow(origin, b, "#56C8AF")
    sum_arrow = arrow(origin, result, foreground)
    parallelogram = m.Polygon(
        origin, a, result, b, fill_color=accent, fill_opacity=0.1, stroke_width=0
    )
    ghost_b = m.DashedLine(origin, b, color="#56C8AF", stroke_width=2)
    other_side = m.DashedLine(b, result, color=accent, stroke_width=2)
    law = _formula(r"\vec a+\vec b=\vec c", foreground, size=35).move_to([0, 2.1, 0])
    values = _formula(
        rf"({ax:g},{ay:g})+({bx:g},{by:g})=({ax + bx:g},{ay + by:g})",
        foreground,
        size=30,
    ).move_to([0, -2.2, 0])
    scene.play(m.Create(plane), m.Write(law), run_time=duration * 0.2)
    scene.play(
        m.GrowArrow(a_arrow) if isinstance(a_arrow, m.Arrow) else m.FadeIn(a_arrow),
        m.GrowArrow(b_arrow) if isinstance(b_arrow, m.Arrow) else m.FadeIn(b_arrow),
        run_time=duration * 0.2,
    )
    scene.add(ghost_b)
    scene.play(
        b_arrow.animate.shift(a - origin),
        m.FadeIn(parallelogram),
        m.Create(other_side),
        run_time=duration * 0.25,
    )
    scene.play(
        m.GrowArrow(sum_arrow)
        if isinstance(sum_arrow, m.Arrow)
        else m.FadeIn(sum_arrow),
        m.Write(values),
        run_time=duration * 0.2,
    )
    scene.wait(duration * 0.15)
    return m.VGroup(
        plane,
        parallelogram,
        ghost_b,
        other_side,
        a_arrow,
        b_arrow,
        sum_arrow,
        law,
        values,
    )


def animate_math(
    scene: m.Scene,
    visual: str,
    options: dict[str, object],
    accent: str,
    foreground: str,
    duration: float,
) -> m.VGroup:
    """Animate one validated math topic and return its live objects for the outro.

    Args:
        scene: Scene receiving the mathematical animation.
        visual: Equation, graph, geometry, calculus or vectors.
        options: Reviewed, structured mathematical values; never Python source.
        accent: Curve and mathematical accent color.
        foreground: Contrast-checked labels and axis color.
        duration: Exact animation time budget, excluding the title and outro.

    Returns:
        Live mathematical objects to remove together at the end of the shot.
    """
    animations = {
        "equation": _animate_equation,
        "graph": _animate_graph,
        "geometry": _animate_geometry,
        "calculus": _animate_calculus,
        "vectors": _animate_vectors,
    }
    return animations[visual](scene, options, accent, foreground, duration)
