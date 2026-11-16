# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT

"""Bounded scene descriptions whose content and timeline come from the storyboard."""

from __future__ import annotations

import math
import re
from typing import cast

COMPOSITION_KINDS = (
    "text",
    "equation",
    "rectangle",
    "circle",
    "line",
    "arrow",
    "polygon",
)

_TIME = {"type": "number", "minimum": 0, "maximum": 1}
_X = {"type": "number", "minimum": -6, "maximum": 6}
_Y = {"type": "number", "minimum": -3, "maximum": 3}
_COLOR = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
_WINDOW_PROPERTIES: dict[str, object] = {
    "start": {
        **_TIME,
        "description": "Exit begins after the entrance and any motion have finished.",
    },
    "end": {**_TIME, "description": "Exit finishes; must be greater than exit.start."},
}
_WINDOW: dict[str, object] = {
    "type": "object",
    "properties": _WINDOW_PROPERTIES,
    "required": ["start", "end"],
    "additionalProperties": False,
}
_MOTION: dict[str, object] = {
    "type": "object",
    "description": (
        "Move on an independent scene timeline, which may overlap appearance. "
        "0 <= motion.start < motion.end <= 1. x/y are the final absolute center, not the "
        "starting position or a displacement. For requested movement, choose a "
        "different final center in the requested direction."
    ),
    "properties": {
        "start": {
            **_TIME,
            "description": "Motion begins on its own timeline and may overlap appearance.",
        },
        "end": {
            **_TIME,
            "description": "Motion finishes; must be > motion.start and <= 1.",
        },
        "x": {
            **_X,
            "description": (
                "FINAL center x. Increasing from initial x moves right; decreasing "
                "moves left. Must differ from initial x for horizontal movement."
            ),
        },
        "y": {
            **_Y,
            "description": (
                "FINAL center y. Increasing from initial y moves up; decreasing "
                "moves down. Must differ from initial y for vertical movement."
            ),
        },
    },
    "required": ["start", "end", "x", "y"],
    "additionalProperties": False,
}
_POINT: dict[str, object] = {
    "type": "array",
    "items": {"type": "number", "minimum": -6, "maximum": 6},
    "minItems": 2,
    "maxItems": 2,
    "description": "Exactly [x,y]: x=-6..6, y=-3..3; validated before rendering.",
}

COMPOSITION_SCHEMA: dict[str, object] = {
    "type": "object",
    "description": (
        "A composition uses only supplied text and geometry. Coordinates are scene "
        "units: x from -6 to 6 and y from -3 to 3. Each element's start/end is its "
        "entrance window, as fractions of scene duration; end finishes appearance, "
        "not visibility. The element stays visible afterwards. Supply explicit "
        "initial positions before choosing final motion destinations. Optional "
        "motion may overlap its entrance. Exit begins after both appearance and "
        "any motion have finished."
    ),
    "properties": {
        "elements": {
            "type": "array",
            "minItems": 1,
            "maxItems": 24,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(COMPOSITION_KINDS)},
                    "text": {"type": "string", "minLength": 1, "maxLength": 300},
                    "x": {
                        **_X,
                        "description": "INITIAL center x before any motion; +x is right.",
                    },
                    "y": {
                        **_Y,
                        "description": "INITIAL center y before any motion; +y is up.",
                    },
                    "color": _COLOR,
                    "fill_color": _COLOR,
                    "fill_opacity": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "stroke_width": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 12,
                    },
                    "font_size": {
                        "type": "number",
                        "minimum": 12,
                        "maximum": 100,
                    },
                    "width": {"type": "number", "minimum": 0.1, "maximum": 12},
                    "height": {"type": "number", "minimum": 0.1, "maximum": 6},
                    "radius": {"type": "number", "minimum": 0.05, "maximum": 3},
                    "points": {
                        "type": "array",
                        "items": _POINT,
                        "minItems": 2,
                        "maxItems": 16,
                    },
                    "start": {
                        **_TIME,
                        "description": "Appearance begins; must be less than end.",
                    },
                    "end": {
                        **_TIME,
                        "description": (
                            "Appearance finishes, NOT disappearance or lifetime. "
                            "The element remains visible. Motion uses an independent "
                            "window and may overlap appearance."
                        ),
                    },
                    "entrance": {
                        "type": "string",
                        "enum": ["fade", "write", "create", "none"],
                    },
                    "motion": _MOTION,
                    "exit": _WINDOW,
                },
                "required": ["kind", "start", "end"],
                "additionalProperties": False,
                "description": (
                    "text/equation require text; rectangle requires width/height; "
                    "circle requires radius; line/arrow require exactly two points; "
                    "polygon requires 3 to 16 points. Point-based shapes use absolute "
                    "points, without x/y. Only text/equation accept font_size."
                ),
            },
        }
    },
    "required": ["elements"],
    "additionalProperties": False,
}

_COMMON = {"kind", "start", "end", "entrance", "motion", "exit", "color"}
_STYLE = {"fill_color", "fill_opacity", "stroke_width"}
_PROPERTIES = {
    "text": {"text", "x", "y", "font_size"},
    "equation": {"text", "x", "y", "font_size"},
    "rectangle": {"x", "y", "width", "height", *_STYLE},
    "circle": {"x", "y", "radius", *_STYLE},
    "line": {"points", "stroke_width"},
    "arrow": {"points", "stroke_width"},
    "polygon": {"points", *_STYLE},
}
_REQUIRED = {
    "text": {"text"},
    "equation": {"text"},
    "rectangle": {"width", "height"},
    "circle": {"radius"},
    "line": {"points"},
    "arrow": {"points"},
    "polygon": {"points"},
}
_BOUNDS = {
    "x": (-6, 6),
    "y": (-3, 3),
    "start": (0, 1),
    "end": (0, 1),
    "font_size": (12, 100),
    "width": (0.1, 12),
    "height": (0.1, 6),
    "radius": (0.05, 3),
    "fill_opacity": (0, 1),
    "stroke_width": (0, 12),
}


def _kind_schemas(properties: dict[str, object]) -> list[dict[str, object]]:
    """Keep generation choices aligned with each primitive's actual fields."""
    return [
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": [kind]},
                "start": properties["start"],
                "end": properties["end"],
                **{key: properties[key] for key in sorted(_REQUIRED[kind])},
                **{
                    key: properties[key]
                    for key in ("x", "y")
                    if key in _PROPERTIES[kind]
                },
                **{
                    key: properties[key]
                    for key in sorted(
                        (_COMMON | _PROPERTIES[kind])
                        - _REQUIRED[kind]
                        - {
                            "kind",
                            "start",
                            "end",
                            "x",
                            "y",
                            "entrance",
                            "motion",
                            "exit",
                        }
                    )
                },
                "entrance": properties["entrance"],
                "motion": properties["motion"],
                "exit": properties["exit"],
            },
            "required": [
                "kind",
                "start",
                "end",
                *sorted(_REQUIRED[kind]),
                *(key for key in ("x", "y") if key in _PROPERTIES[kind]),
            ],
            "additionalProperties": False,
        }
        for kind in COMPOSITION_KINDS
    ]


_SCHEMA_PROPERTIES = cast(dict[str, object], COMPOSITION_SCHEMA["properties"])
_ELEMENTS_SCHEMA = cast(dict[str, object], _SCHEMA_PROPERTIES["elements"])
_ELEMENT_SCHEMA = cast(dict[str, object], _ELEMENTS_SCHEMA["items"])
_ELEMENTS_SCHEMA["items"] = {
    "anyOf": _kind_schemas(cast(dict[str, object], _ELEMENT_SCHEMA["properties"]))
}


def _object(value: object, allowed: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object.")
    result = cast(dict[str, object], value)
    extra = result.keys() - allowed
    if extra:
        raise ValueError(
            f"{name} contains unsupported fields: {', '.join(sorted(extra))}."
        )
    return result


def _number(value: object, low: float, high: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low <= value <= high
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a number between {low:g} and {high:g}.")
    return float(value)


def _window(
    value: object, name: str, after: float, *, motion: bool = False
) -> dict[str, object]:
    required = {"start", "end", "x", "y"} if motion else {"start", "end"}
    source = _object(value, required, name)
    if not required <= source.keys():
        raise ValueError(f"{name} requires {', '.join(sorted(required))}.")
    result: dict[str, object] = {
        key: _number(source[key], *_BOUNDS[key], f"{name} {key}") for key in source
    }
    start, end = cast(float, result["start"]), cast(float, result["end"])
    if start < after or end <= start:
        raise ValueError(
            f"{name} must start after the previous action and end after its start."
        )
    return result


def _points(value: object, kind: str, name: str) -> list[list[float]]:
    low, high = (3, 16) if kind == "polygon" else (2, 2)
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise ValueError(f"{name} needs {low} to {high} points.")
    points: list[list[float]] = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"{name} points must be [x, y] pairs.")
        points.append(
            [
                _number(point[0], -6, 6, f"{name} x"),
                _number(point[1], -3, 3, f"{name} y"),
            ]
        )
    if kind in {"line", "arrow"}:
        if math.dist(points[0], points[1]) < 0.01:
            raise ValueError(f"{name} endpoints must be at least 0.01 units apart.")
    else:
        area = (
            abs(
                sum(
                    point[0] * points[(index + 1) % len(points)][1]
                    - points[(index + 1) % len(points)][0] * point[1]
                    for index, point in enumerate(points)
                )
            )
            / 2
        )
        if area < 0.001:
            raise ValueError(f"{name} polygon must have a nonzero area.")
    return points


def _element(value: object, index: int) -> dict[str, object]:
    name = f"Composition element {index + 1}"
    source = _object(value, _COMMON | set.union(*_PROPERTIES.values()), name)
    kind = source.get("kind")
    if not isinstance(kind, str) or kind not in COMPOSITION_KINDS:
        raise ValueError(f"{name} needs a supported kind.")
    source = _object(source, _COMMON | _PROPERTIES[kind], name)
    required = {"kind", "start", "end"} | _REQUIRED[kind]
    if not required <= source.keys():
        missing = ", ".join(sorted(required - source.keys()))
        raise ValueError(f"{name} requires {missing}; content is never substituted.")
    result: dict[str, object] = {"kind": kind}
    for key in source.keys() & _BOUNDS.keys():
        result[key] = _number(source[key], *_BOUNDS[key], f"{name} {key}")
    start, end = cast(float, result["start"]), cast(float, result["end"])
    if end <= start:
        raise ValueError(f"{name} end must exceed start.")
    if "text" in source:
        text = source["text"]
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > 300
            or any(ord(character) < 32 and character != "\n" for character in text)
        ):
            raise ValueError(f"{name} text must contain 1 to 300 printable characters.")
        if kind == "equation" and "\n" in text:
            raise ValueError(f"{name} equation must be a single line of LaTeX.")
        result["text"] = text
    for key in ("color", "fill_color"):
        if key in source:
            color = source[key]
            if (
                not isinstance(color, str)
                or re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None
            ):
                raise ValueError(f"{name} {key} must be a #RRGGBB color.")
            result[key] = color.upper()
    if "points" in source:
        result["points"] = _points(source["points"], kind, name)
    if "entrance" in source:
        entrance = source["entrance"]
        if entrance not in ("fade", "write", "create", "none"):
            raise ValueError(f"{name} entrance must be fade, write, create or none.")
        result["entrance"] = entrance
    last = end
    if "motion" in source:
        motion = _window(source["motion"], f"{name} motion", 0, motion=True)
        result["motion"] = motion
        last = max(last, cast(float, motion["end"]))
    if "exit" in source:
        result["exit"] = _window(source["exit"], f"{name} exit", last)
    return result


def validate_composition(value: object) -> dict[str, object]:
    """Validate declarative content without filling in a topic, geometry or timeline.

    Args:
        value: A JSON object containing an ordered list of scene elements.

    Returns:
        A fresh, bounded composition with numeric values and colors normalized.

    Raises:
        ValueError: If elements, coordinates, content or timeline actions are invalid.
    """
    source = _object(value, {"elements"}, "Composition")
    elements = source.get("elements")
    if not isinstance(elements, list) or not 1 <= len(elements) <= 24:
        raise ValueError(
            "Composition requires 1 to 24 elements; add the intended scene content."
        )
    return {
        "elements": [_element(value, index) for index, value in enumerate(elements)]
    }
