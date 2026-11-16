# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT

"""Scene content and timing must be supplied, bounded and declarative."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from studio.composition_spec import (
    COMPOSITION_KINDS,
    COMPOSITION_SCHEMA,
    validate_composition,
)


def _element(**values: object) -> dict[str, object]:
    return {
        "kind": "text",
        "text": "User's actual words",
        "start": 0,
        "end": 0.2,
        **values,
    }


@pytest.mark.parametrize(
    "element",
    [
        _element(text="  Keep spacing\nand the actual topic  "),
        _element(kind="equation", text=r"E=mc^2"),
        {"kind": "rectangle", "width": 2, "height": 1, "start": 0.1, "end": 0.3},
        {"kind": "circle", "radius": 0.8, "start": 0.2, "end": 0.6},
        {"kind": "line", "points": [[-2, -1], [3, 2]], "start": 0, "end": 0.4},
        {"kind": "arrow", "points": [[-1, 0], [1, 0]], "start": 0.1, "end": 0.5},
        {"kind": "polygon", "points": [[0, 0], [2, 0], [0, 1]], "start": 0, "end": 1},
    ],
)
def test_each_supported_element_preserves_only_the_supplied_content(
    element: dict[str, object],
) -> None:
    original = {"elements": [element]}
    before = deepcopy(original)
    validated = validate_composition(original)
    assert validated == original
    assert original == before
    assert validated is not original
    assert validated["elements"] is not original["elements"]


def test_separate_timelines_and_styles_are_normalized_without_content_defaults() -> (
    None
):
    source = {
        "elements": [
            _element(
                color="#aabbcc",
                entrance="write",
                x=-2,
                y=1,
                font_size=52,
                motion={"start": 0.4, "end": 0.7, "x": 3, "y": -2},
                exit={"start": 0.9, "end": 1},
            )
        ]
    }
    result = validate_composition(source)
    assert result == {
        "elements": [
            _element(
                color="#AABBCC",
                entrance="write",
                x=-2.0,
                y=1.0,
                font_size=52.0,
                motion={"start": 0.4, "end": 0.7, "x": 3.0, "y": -2.0},
                exit={"start": 0.9, "end": 1.0},
            )
        ]
    }
    assert "fill_color" not in cast(list[dict[str, object]], result["elements"])[0]


@pytest.mark.parametrize(
    ("appearance", "movement", "exit_window"),
    [
        ((0.0, 1.0), (0.25, 0.75), None),
        ((0.1, 0.6), (0.25, 0.75), (0.75, 0.95)),
        ((0.1, 0.7), (0.25, 0.5), (0.7, 0.95)),
        ((0.2, 0.5), (0.0, 0.3), (0.5, 0.9)),
    ],
)
def test_concurrent_appearance_and_movement_preserve_authored_timing(
    appearance: tuple[float, float],
    movement: tuple[float, float],
    exit_window: tuple[float, float] | None,
) -> None:
    element: dict[str, object] = {
        "kind": "circle",
        "radius": 0.5,
        "x": -3,
        "y": 0,
        "start": appearance[0],
        "end": appearance[1],
        "motion": {"start": movement[0], "end": movement[1], "x": 3, "y": 0},
    }
    if exit_window is not None:
        element["exit"] = {"start": exit_window[0], "end": exit_window[1]}
    source = {"elements": [element]}
    authored = deepcopy(source)
    assert validate_composition(source) == authored
    assert source == authored


@pytest.mark.parametrize(
    ("appearance_end", "motion_end", "exit_start"),
    [(0.6, 0.4, 0.5), (0.2, 0.8, 0.7), (1.0, 0.75, 0.9)],
)
def test_exit_cannot_collide_with_either_appearance_or_movement(
    appearance_end: float, motion_end: float, exit_start: float
) -> None:
    source = {
        "elements": [
            _element(
                end=appearance_end,
                motion={"start": 0.1, "end": motion_end, "x": 1, "y": 0},
                exit={"start": exit_start, "end": 1},
            )
        ]
    }
    with pytest.raises(ValueError, match="exit must start after the previous action"):
        validate_composition(source)


@pytest.mark.parametrize("kind", COMPOSITION_KINDS)
def test_content_is_never_replaced_with_an_example(kind: str) -> None:
    with pytest.raises(ValueError, match=r"requires.*content is never substituted"):
        validate_composition({"elements": [{"kind": kind, "start": 0, "end": 1}]})


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"elements": []},
        {"elements": [_element()] * 25},
        {"elements": [_element()], "code": "pass"},
    ],
)
def test_missing_oversized_or_executable_compositions_are_rejected(
    value: object,
) -> None:
    with pytest.raises(ValueError, match="Composition"):
        validate_composition(value)


@pytest.mark.parametrize(
    "element",
    [
        _element(text=""),
        _element(text=" \n "),
        _element(text="x" * 301),
        _element(text="tab\tcontent"),
        _element(text="control\x00"),
        _element(kind="equation", text="x\ny"),
        _element(x=True),
        _element(x=float("inf")),
        _element(x=float("nan")),
        _element(x=10**1000),
        _element(y=3.1),
        _element(font_size=101),
        _element(color="red"),
        _element(color="url(https://example.com/image.svg)"),
        _element(kind="video", text="topic"),
        _element(code="print(123)"),
        _element(src="C:/secret.txt"),
        _element(font="file:///private.otf"),
        _element(fill_opacity=1),
        _element(width=2),
        _element(start=-0.1),
        _element(start=0.2, end=0.2),
        _element(start=0.3, end=0.2),
        _element(end=1.1),
        _element(entrance="execute"),
        _element(motion={"start": -0.1, "end": 0.7, "x": 0, "y": 0}),
        _element(motion={"start": 0.3, "end": 0.7, "x": 0}),
        _element(motion={"start": 0.3, "end": 0.7, "x": 0, "y": 0, "path": "file"}),
        _element(motion={"start": 0.7, "end": 0.3, "x": 0, "y": 0}),
        _element(exit={"start": 0.1, "end": 1}),
        _element(exit={"start": 0.9, "end": 0.9}),
        _element(exit={"start": 0.9, "end": 1.1}),
        _element(
            motion={"start": 0.3, "end": 0.8, "x": 0, "y": 0},
            exit={"start": 0.7, "end": 1},
        ),
    ],
)
def test_unbounded_or_unsupported_element_data_is_rejected(
    element: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="Composition element"):
        validate_composition({"elements": [element]})


@pytest.mark.parametrize(
    ("kind", "points"),
    [
        ("line", [[0, 0]]),
        ("arrow", [[0, 0], [1, 1], [2, 2]]),
        ("line", [[0, 0], [0, 0]]),
        ("arrow", [[0, 0], [0.001, 0]]),
        ("line", [[0, 0, 0], [1, 1]]),
        ("line", [[0, 0], [7, 0]]),
        ("line", [[0, 0], [0, float("nan")]]),
        ("polygon", [[0, 0], [1, 0]]),
        ("polygon", [[0, 0], [1, 0], [2, 0]]),
        ("polygon", [[0, 0]] * 17),
    ],
)
def test_point_shapes_reject_invalid_or_degenerate_coordinates(
    kind: str, points: object
) -> None:
    with pytest.raises(ValueError, match="Composition element"):
        validate_composition(
            {"elements": [{"kind": kind, "points": points, "start": 0, "end": 1}]}
        )


def test_points_are_copied_and_cannot_be_mutated_through_the_input() -> None:
    points = [[0, 0], [1, 2]]
    result = validate_composition(
        {"elements": [{"kind": "line", "points": points, "start": 0, "end": 1}]}
    )
    points[1][1] = 3
    elements = cast(list[dict[str, object]], result["elements"])
    assert elements[0]["points"] == [[0, 0], [1, 2]]


def test_generation_schema_uses_array_item_objects_supported_by_local_ollama() -> None:
    def check(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "array":
                assert isinstance(value["items"], dict)
                assert "prefixItems" not in value
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(COMPOSITION_SCHEMA)


def test_runtime_keeps_stricter_vertical_point_bounds_than_generation_grammar() -> None:
    with pytest.raises(ValueError, match="y must be a number between -3 and 3"):
        validate_composition(
            {
                "elements": [
                    {"kind": "line", "points": [[0, 0], [1, 4]], "start": 0, "end": 1}
                ]
            }
        )


def test_generation_variants_require_content_and_exclude_other_kinds_fields() -> None:
    properties = cast(dict[str, object], COMPOSITION_SCHEMA["properties"])
    elements = cast(dict[str, object], properties["elements"])
    items = cast(dict[str, object], elements["items"])
    variants = cast(list[dict[str, object]], items["anyOf"])
    expected: dict[str, tuple[set[str], set[str]]] = {
        "text": (
            {"text", "x", "y"},
            {"width", "height", "radius", "points", "fill_opacity"},
        ),
        "equation": (
            {"text", "x", "y"},
            {"width", "height", "radius", "points", "fill_opacity"},
        ),
        "rectangle": (
            {"width", "height", "x", "y"},
            {"text", "points", "radius", "font_size"},
        ),
        "circle": (
            {"radius", "x", "y"},
            {"text", "points", "width", "height", "font_size"},
        ),
        "line": (
            {"points"},
            {
                "text",
                "x",
                "y",
                "width",
                "height",
                "radius",
                "font_size",
                "fill_opacity",
            },
        ),
        "arrow": (
            {"points"},
            {
                "text",
                "x",
                "y",
                "width",
                "height",
                "radius",
                "font_size",
                "fill_opacity",
            },
        ),
        "polygon": (
            {"points"},
            {"text", "x", "y", "width", "height", "radius", "font_size"},
        ),
    }
    seen: set[str] = set()
    for variant in variants:
        fields = cast(dict[str, object], variant["properties"])
        assert list(fields)[:3] == ["kind", "start", "end"]
        assert cast(list[str], variant["required"])[:3] == ["kind", "start", "end"]
        kind_schema = cast(dict[str, object], fields["kind"])
        kind = cast(list[str], kind_schema["enum"])[0]
        seen.add(kind)
        content, excluded = expected[kind]
        assert content | {"kind", "start", "end"} == set(
            cast(list[str], variant["required"])
        )
        assert not excluded & fields.keys()
        ordering = list(fields)
        assert all(ordering.index(key) < ordering.index("motion") for key in content)
        assert ordering[-3:] == ["entrance", "motion", "exit"]
        assert variant["additionalProperties"] is False
    assert seen == set(COMPOSITION_KINDS)


def test_generation_positions_do_not_change_editor_center_defaults() -> None:
    supplied = {"elements": [_element()]}
    assert validate_composition(supplied) == supplied
    assert "x" not in supplied["elements"][0]


def test_generation_descriptions_distinguish_initial_position_and_action_windows() -> (
    None
):
    properties = cast(dict[str, object], COMPOSITION_SCHEMA["properties"])
    elements = cast(dict[str, object], properties["elements"])
    items = cast(dict[str, object], elements["items"])
    variants = cast(list[dict[str, object]], items["anyOf"])
    fields = cast(dict[str, object], variants[0]["properties"])
    end = cast(dict[str, object], fields["end"])
    assert "NOT disappearance or lifetime" in str(end["description"])
    assert "may overlap appearance" in str(end["description"])
    assert "INITIAL center" in str(cast(dict[str, object], fields["x"])["description"])
    motion = cast(dict[str, object], fields["motion"])
    assert "independent scene timeline" in str(motion["description"])
    motion_fields = cast(dict[str, object], motion["properties"])
    final_x = cast(dict[str, object], motion_fields["x"])
    assert "FINAL center" in str(final_x["description"])
    assert "Increasing from initial x moves right" in str(final_x["description"])
