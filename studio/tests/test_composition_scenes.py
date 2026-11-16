# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT

"""Real ManimGX primitives follow user positions, content and animation windows."""

from __future__ import annotations

from typing import cast

import numpy as np
import pytest
from studio.composition_scenes import (
    _make_element,
    _motion_track,
    _track,
    animate_composition,
)
from studio.composition_spec import validate_composition

import manimgx as m
from manimgx.animation.timeline import windows


def _element(kind: str, **values: object) -> dict[str, object]:
    return {"kind": kind, "start": 0, "end": 0.2, **values}


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        (_element("text", text="Gravity is a force", x=-3, y=1), m.Text),
        (_element("equation", text=r"F=ma", x=2, y=-1), m.MathTex),
        (_element("rectangle", width=3, height=1, x=1, y=2), m.Rectangle),
        (_element("circle", radius=0.4, x=-2, y=-1), m.Circle),
        (_element("line", points=[[-4, -1], [-1, 2]]), m.Line),
        (_element("arrow", points=[[0, 0], [4, 1]]), m.Arrow),
        (_element("polygon", points=[[-1, 0], [1, 0], [0, 2]]), m.Polygon),
    ],
)
def test_native_elements_use_supplied_geometry_and_content(
    element: dict[str, object], expected: type[m.VMobject]
) -> None:
    validated = validate_composition({"elements": [element]})
    result = _make_element(
        cast(list[dict[str, object]], validated["elements"])[0], "#43DD8D", "#FFFFFF"
    )
    assert isinstance(result, expected)
    assert np.isfinite(result.points).all()
    if element["kind"] in {"text", "equation", "rectangle", "circle"}:
        assert result.get_center() == pytest.approx(
            [element.get("x", 0), element.get("y", 0), 0]
        )
    if isinstance(result, m.Text):
        assert result.text == element["text"]
    if isinstance(result, m.MathTex):
        assert result.tex_string == element["text"]
    if element["kind"] == "rectangle":
        assert result.width == pytest.approx(3)
        assert result.height == pytest.approx(1)
    if element["kind"] == "circle":
        assert result.width == pytest.approx(0.8)
    if isinstance(result, m.Line):
        points = cast(list[list[float]], element["points"])
        assert result.get_start() == pytest.approx([*points[0], 0])
        assert result.get_end() == pytest.approx([*points[1], 0])


def test_supplied_shape_styles_override_generic_scene_colors() -> None:
    obj = _make_element(
        _element(
            "circle",
            radius=1,
            color="#ABCDEF",
            fill_color="#102030",
            fill_opacity=0.7,
            stroke_width=6,
        ),
        "#43DD8D",
        "#FFFFFF",
    )
    assert obj.stroke_color == m.ManimColor("#ABCDEF")
    assert obj.fill_color == m.ManimColor("#102030")
    assert obj.fill_opacity == pytest.approx(0.7)
    assert obj.stroke_width == pytest.approx(6)


def test_entrance_motion_and_exit_windows_match_user_timeline_exactly() -> None:
    element = _element(
        "circle",
        radius=0.5,
        start=0.15,
        end=0.3,
        entrance="create",
        motion={"start": 0.4, "end": 0.7, "x": 2, "y": -1},
        exit={"start": 0.8, "end": 0.9},
    )
    obj = _make_element(element, "#43DD8D", "#FFFFFF")
    track = _track(obj, element, 10)
    assert track.run_time == pytest.approx(10)
    actions = [
        window
        for window in windows(track)
        if isinstance(window.part, (m.Create, m.FadeOut))
    ]
    assert np.array(
        [
            (
                float(window.opens) * track.run_time,
                float(window.closes or 0) * track.run_time,
            )
            for window in actions
        ]
    ) == pytest.approx(np.array([(1.5, 3), (8, 9)]))
    motion = _motion_track(obj, element, 10)
    assert motion.run_time == pytest.approx(10)
    motion.update_function(obj, 0.55)
    assert obj.get_center() == pytest.approx([1, -0.5, 0])


@pytest.mark.parametrize("entrance", ["fade", "write", "create", "none"])
def test_real_concurrent_animation_has_exact_duration_and_custom_final_position(
    entrance: str,
) -> None:
    composition = validate_composition(
        {
            "elements": [
                _element(
                    "text",
                    text="A custom topic",
                    x=-3,
                    y=2,
                    start=0.1,
                    end=0.3,
                    entrance=entrance,
                ),
                _element(
                    "rectangle",
                    width=1.2,
                    height=0.4,
                    x=-1,
                    y=-1,
                    start=0.2,
                    end=0.4,
                    entrance=entrance,
                    motion={"start": 0.5, "end": 0.8, "x": 3, "y": 0.5},
                ),
            ]
        }
    )
    scene = m.Scene()
    group = animate_composition(scene, composition, "#43DD8D", "#FFFFFF", 2.75)
    assert scene.time == pytest.approx(2.75)
    assert len(group) == 2
    assert group[0].get_center() == pytest.approx([-3, 2, 0])
    assert group[1].get_center() == pytest.approx([3, 0.5, 0])
    assert group[0] in scene.mobjects
    assert group[1] in scene.mobjects


def test_user_exit_removes_object_while_other_content_remains() -> None:
    composition = validate_composition(
        {
            "elements": [
                _element("text", text="Keep this", entrance="none"),
                _element("circle", radius=0.5, exit={"start": 0.6, "end": 0.8}),
            ]
        }
    )
    scene = m.Scene()
    group = animate_composition(scene, composition, "#43DD8D", "#FFFFFF", 2)
    assert scene.time == pytest.approx(2)
    assert group[0] in scene.mobjects
    assert group[1] not in scene.mobjects


def test_long_user_content_is_fitted_without_changing_words() -> None:
    text = "User supplied science explanation " * 8
    obj = _make_element(
        _element("text", text=text, font_size=100), "#43DD8D", "#FFFFFF"
    )
    assert isinstance(obj, m.Text)
    assert obj.text == text
    assert obj.width <= 12.001
    assert obj.height <= 6.001


@pytest.mark.parametrize(
    ("kind", "entrance"),
    [("circle", "fade"), ("circle", "create"), ("text", "write"), ("circle", "none")],
)
def test_real_frames_overlap_appearance_with_motion_and_preserve_geometry(
    kind: str, entrance: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(m.config, "frame_rate", 40)
    content = {"text": "Moving words"} if kind == "text" else {"radius": 0.5}
    composition = validate_composition(
        {
            "elements": [
                _element(
                    kind,
                    **content,
                    x=-3,
                    y=-1,
                    start=0.2,
                    end=1,
                    entrance=entrance,
                    motion={"start": 0.1, "end": 0.6, "x": 3, "y": 1},
                )
            ]
        }
    )
    element = cast(list[dict[str, object]], composition["elements"])[0]
    original = _make_element(element, "#43DD8D", "#FFFFFF")
    relative = (
        np.vstack([leaf.points for leaf in original.family_members_with_points()])
        - original.get_center()
    )
    positions: dict[int, tuple[float, ...] | None] = {}
    opacity: dict[int, float] = {}

    class MovingScene(m.Scene):
        def construct(self) -> None:
            self.group = animate_composition(self, composition, "#43DD8D", "#FFFFFF", 2)

        def _emit(self, repeat: int = 1) -> None:
            sample(self.frame, repeat)
            super()._emit(repeat)

    scene = MovingScene()

    def sample(first: int, repeat: int) -> None:
        if scene.mobjects:
            obj = scene.mobjects[0]
            center = obj.get_center()
            points = np.vstack(
                [leaf.points for leaf in obj.family_members_with_points()]
            )
            assert points - center == pytest.approx(relative)
            for index in range(first, first + repeat):
                positions[index] = tuple(center)
                opacity[index] = max(
                    max(leaf.fill_opacity, leaf.stroke_opacity)
                    for leaf in obj.family_members_with_points()
                )
        else:
            for index in range(first, first + repeat):
                positions[index] = None

    scene.render()
    assert scene.time == pytest.approx(2)
    assert all(positions[index] is None for index in range(16))
    assert positions[16] == pytest.approx([-1.8, -0.6, 0])
    assert positions[28] == pytest.approx([0, 0, 0])
    assert positions[48] == pytest.approx([3, 1, 0])
    assert positions[64] == pytest.approx([3, 1, 0])
    assert scene.group[0].get_center() == pytest.approx([3, 1, 0])
    if entrance == "fade":
        assert opacity[28] < opacity[64]
        assert opacity[80] == pytest.approx(
            max(original.fill_opacity, original.stroke_opacity)
        )
    scene.remove(*scene.group.get_family())
    assert not scene.mobjects


def test_real_motion_track_does_not_reintroduce_an_exited_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m.config, "frame_rate", 40)
    composition = validate_composition(
        {
            "elements": [
                _element(
                    "circle",
                    radius=0.5,
                    x=-3,
                    start=0.2,
                    end=0.6,
                    motion={"start": 0.1, "end": 0.8, "x": 3, "y": 0},
                    exit={"start": 0.8, "end": 0.9},
                )
            ]
        }
    )
    visible: dict[int, bool] = {}

    class ExitingScene(m.Scene):
        def construct(self) -> None:
            self.group = animate_composition(self, composition, "#43DD8D", "#FFFFFF", 2)

        def _emit(self, repeat: int = 1) -> None:
            sample(self.frame, repeat)
            super()._emit(repeat)

    scene = ExitingScene()

    def sample(first: int, repeat: int) -> None:
        for index in range(first, first + repeat):
            visible[index] = bool(scene.mobjects)

    scene.render()
    assert scene.time == pytest.approx(2)
    assert not any(visible[index] for index in range(16))
    assert all(visible[index] for index in range(17, 72))
    assert not any(visible[index] for index in range(72, 81))
    assert not scene.mobjects
    assert not scene.group[0].updaters
