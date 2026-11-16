# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT

"""Authored content, timing and soundtrack cross the complete renderer boundary."""

from pathlib import Path
from typing import cast

import pytest
from studio import renderer
from studio.server import validate_plan

import manimgx as m


def test_composition_render_uses_authored_content_without_injected_headings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = validate_plan(
        {
            "title": "Metadata only",
            "mode": "anime",
            "scenes": [
                {
                    "title": "Also metadata only",
                    "narration": "",
                    "visual": "composition",
                    "duration": 7.25,
                    "background": "#162033",
                    "accent": "#8DABFF",
                    "composition": {
                        "elements": [
                            {
                                "kind": "text",
                                "text": "User's own scene",
                                "x": -2,
                                "y": 1,
                                "start": 0.1,
                                "end": 0.25,
                                "motion": {"start": 0.4, "end": 0.8, "x": 2, "y": -1},
                            }
                        ]
                    },
                }
            ],
            "music": {"tempo": 90, "chords": [[50, 57], [53, 60, 65]]},
        }
    )
    captured_text: list[str] = []
    original_text = m.Text

    def text(content: str, **kwargs: object) -> m.Text:
        captured_text.append(content)
        return original_text(content, **kwargs)  # ty: ignore[invalid-argument-type]

    def render(scene: m.Scene, path: Path, *, preset: str, crf: float) -> None:
        scene.construct()
        assert scene.time == pytest.approx(7.25)
        assert not scene.mobjects
        path.write_bytes(b"authored render")

    scores: list[dict[str, object] | None] = []

    def music(
        path: Path,
        duration: float,
        volume: float,
        score: dict[str, object] | None = None,
    ) -> None:
        assert duration == 7.25
        scores.append(score)
        path.write_bytes(b"test score")

    monkeypatch.setattr(m, "Text", text)
    monkeypatch.setattr(m.Scene, "render", render)
    monkeypatch.setattr(m.Scene, "add_sound", lambda *args, **kwargs: None)
    monkeypatch.setattr(renderer, "_make_music", music)
    shots = renderer._prepare_shots(plan, tmp_path, {}, lambda _message: None)
    assert (
        shots[0].composition
        == cast(list[dict[str, object]], plan["scenes"])[0]["composition"]
    )
    output = renderer.render_project(
        plan, tmp_path, {"music_enabled": True}, lambda _message: None
    )
    assert output.read_bytes() == b"authored render"
    assert captured_text == ["User's own scene"]
    assert scores == [plan["music"]]
