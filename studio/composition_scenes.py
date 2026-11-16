# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT

"""Render storyboard-defined geometry and independent animation timelines."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import manimgx as m


def _number(element: dict[str, object], key: str, default: float = 0) -> float:
    return cast(float, element.get(key, default))


def _make_element(
    element: dict[str, object], accent: str, foreground: str
) -> m.VMobject:
    import manimgx as m

    kind = element["kind"]
    color = cast(
        str,
        element.get("color", foreground if kind in {"text", "equation"} else accent),
    )
    if kind in {"text", "equation"}:
        text = cast(str, element["text"])
        size = _number(element, "font_size", 36)
        result = (
            m.Text(text, font="Noto Sans", font_size=size, color=color)
            if kind == "text"
            else m.MathTex(text, font_size=size, color=color)
        )
        if result.width > 12:
            result.scale_to_fit_width(12)
        if result.height > 6:
            result.scale_to_fit_height(6)
    elif kind == "rectangle":
        result = m.Rectangle(
            width=_number(element, "width"), height=_number(element, "height")
        )
    elif kind == "circle":
        result = m.Circle(radius=_number(element, "radius"))
    else:
        points = [[x, y, 0] for x, y in cast(list[list[float]], element["points"])]
        if kind == "line":
            result = m.Line(points[0], points[1])
        elif kind == "arrow":
            result = m.Arrow(points[0], points[1], buff=0)
        else:
            result = m.Polygon(*points)
    if kind not in {"text", "equation"}:
        result.set_stroke(color=color, width=_number(element, "stroke_width", 2))
        result.set_fill(
            color=cast(str, element.get("fill_color", color)),
            opacity=_number(element, "fill_opacity", 0),
        )
    if kind not in {"line", "arrow", "polygon"}:
        result.move_to([_number(element, "x"), _number(element, "y"), 0])
    return result


def _track(
    obj: m.VMobject, element: dict[str, object], duration: float
) -> m.Succession:
    import manimgx as m

    start, end = _number(element, "start"), _number(element, "end")
    parts: list[m.Animation] = []
    if start:
        parts.append(m.Wait(start * duration))
    entrance = element.get("entrance", "fade")
    introduction = {
        "fade": m.FadeIn,
        "write": m.Write,
        "create": m.Create,
        "none": m.Add,
    }[cast(str, entrance)]
    parts.append(introduction(obj, run_time=(end - start) * duration))
    last = end
    if "motion" in element:
        motion = cast(dict[str, object], element["motion"])
        last = max(last, _number(motion, "end"))
        if last > end:
            parts.append(m.Wait((last - end) * duration))
    if "exit" in element:
        exit_window = cast(dict[str, object], element["exit"])
        start, end = _number(exit_window, "start"), _number(exit_window, "end")
        if start > last:
            parts.append(m.Wait((start - last) * duration))
        parts.append(m.FadeOut(obj, run_time=(end - start) * duration))
        last = end
    if last < 1:
        parts.append(m.Wait((1 - last) * duration))
    return m.Succession(*parts)


def _motion_track(
    obj: m.VMobject, element: dict[str, object], duration: float
) -> m.UpdateFromAlphaFunc[m.VMobject]:
    import manimgx as m

    motion = cast(dict[str, object], element["motion"])
    start, end = _number(motion, "start"), _number(motion, "end")
    initial = obj.get_center().copy()
    destination = initial.copy()
    destination[:] = [_number(motion, "x"), _number(motion, "y"), 0]
    displacement = destination - initial

    def position(mobject: m.VMobject, alpha: float) -> None:
        fraction = min(1.0, max(0.0, (alpha - start) / (end - start)))
        # Create and Write trim paint, preserving the complete geometry's center.
        # Running after appearance tracks also holds the destination while a longer
        # entrance continues to interpolate its original positions.
        mobject.move_to(initial + displacement * fraction)

    return m.UpdateFromAlphaFunc(obj, position, run_time=duration, rate_func=m.linear)


def animate_composition(
    scene: m.Scene,
    composition: dict[str, object],
    accent: str,
    foreground: str,
    duration: float,
) -> m.VGroup:
    """Play user-defined elements concurrently for an exact scene duration.

    Args:
        scene: Scene receiving the visual objects and their animation tracks.
        composition: Declarative content accepted by validate_composition.
        accent: Default shape color when an element omits its own color.
        foreground: Default text color chosen for the scene background.
        duration: Total scene duration, in seconds.

    Returns:
        The composition's objects for removal before the following scene.
    """
    import manimgx as m

    elements = cast(list[dict[str, object]], composition["elements"])
    objects = [_make_element(element, accent, foreground) for element in elements]
    paired = list(zip(objects, elements, strict=True))
    scene.play(
        m.AnimationGroup(
            *(_track(obj, element, duration) for obj, element in paired),
            *(
                _motion_track(obj, element, duration)
                for obj, element in paired
                if "motion" in element
            ),
            run_time=duration,
            rate_func=m.linear,
        )
    )
    return m.VGroup(*objects)
