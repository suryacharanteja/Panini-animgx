# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
"""Math plans survive local planning and rendering without executable model code."""

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from studio import math_spec, renderer, server
from studio.tests.test_server import math_parameters


def _math_plan(count: int = 2) -> dict[str, object]:
    return {
        "title": "Understanding a parabola",
        "mode": "math",
        "scenes": [
            {
                "title": f"Parabola {index + 1}",
                "narration": "The square of x determines the height.",
                "visual": "graph",
                "duration": 3 + index,
                "background": "#101820",
                "accent": "#6CE5C0",
                "math": {
                    "expression": "(x+1)**2",
                    "x_min": -3,
                    "x_max": 2,
                    "y_min": -1,
                    "y_max": 9,
                },
            }
            for index in range(count)
        ],
    }


def _scenes(plan: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], plan["scenes"])


def _schema_variants(schema: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index complete scene contracts by their single selected visual."""
    properties = server.object_dict(schema["properties"])
    scenes = server.object_dict(properties["scenes"])
    item = server.object_dict(scenes["items"])
    variants = cast(list[dict[str, object]], item["anyOf"])
    result: dict[str, dict[str, object]] = {}
    for variant in variants:
        fields = server.object_dict(variant["properties"])
        choices = server.object_dict(fields["visual"])
        names = cast(list[str], choices["enum"])
        assert len(names) == 1
        assert names[0] not in result
        result[names[0]] = variant
    return result


@pytest.fixture
def application(tmp_path: Path) -> Iterator[server.Application]:
    application = server.Application(tmp_path)
    try:
        yield application
    finally:
        application.executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.parametrize("visual", math_spec.MATH_VISUALS)
def test_math_mode_retains_validated_parameters_without_changing_input(
    visual: str,
) -> None:
    plan = _math_plan(1)
    scene = _scenes(plan)[0]
    scene["visual"] = visual
    parameters = math_parameters(visual)
    scene["math"] = parameters
    original = copy.deepcopy(plan)
    result = server.validate_plan(plan)
    assert result["mode"] == "math"
    assert _scenes(result)[0]["math"] == math_spec.validate_math(visual, parameters)
    assert plan == original
    assert _scenes(result)[0]["math"] is not scene["math"]


def test_math_mode_rejects_invalid_functions_and_equations() -> None:
    for visual, parameters in (
        ("graph", {**math_parameters("graph"), "expression": "__import__('os')"}),
        ("equation", {"equations": ["x" * 201]}),
    ):
        plan = _math_plan(1)
        _scenes(plan)[0].update(visual=visual, math=parameters)
        with pytest.raises(ValueError, match=r"visual|math|equation|LaTeX|Use"):
            server.validate_plan(plan)


@pytest.mark.parametrize(
    "visual", ["orbit", "process", "bars", "character", "landscape"]
)
def test_math_mode_rejects_retired_presets_with_replanning_guidance(
    visual: str,
) -> None:
    plan = _math_plan(1)
    _scenes(plan)[0]["visual"] = visual
    with pytest.raises(ValueError, match="Create a new storyboard"):
        server.validate_plan(plan)


def test_math_planning_schema_requires_real_visuals_and_bounded_parameters() -> None:
    original = copy.deepcopy(server.PLAN_SCHEMA)
    schema = server.planning_schema("math", 30)
    properties = server.object_dict(schema["properties"])
    assert properties["mode"] == {"type": "string", "enum": ["math"]}
    scenes = server.object_dict(properties["scenes"])
    assert (scenes["minItems"], scenes["maxItems"]) == (1, 8)
    item = server.object_dict(scenes["items"])
    assert set(item) == {"anyOf"}
    variants = _schema_variants(schema)
    assert list(variants) == [*math_spec.MATH_VISUALS, "composition"]
    composition = variants["composition"]
    assert "composition" in cast(list[str], composition["required"])
    assert "math" not in server.object_dict(composition["properties"])
    graph = variants["graph"]
    fields = server.object_dict(graph["properties"])
    bounds = server.object_dict(server.object_dict(fields["math"])["properties"])
    assert bounds["x_min"] == {"type": "number", "minimum": -20, "maximum": 20}
    assert bounds["y_max"] == {"type": "number", "minimum": -20, "maximum": 20}
    bounds["x_min"] = {}
    cast(list[str], graph["required"]).clear()
    assert original == server.PLAN_SCHEMA
    fresh = _schema_variants(server.planning_schema("math", 30))["graph"]
    fresh_fields = server.object_dict(fresh["properties"])
    fresh_bounds = server.object_dict(
        server.object_dict(fresh_fields["math"])["properties"]
    )
    assert fresh_bounds["x_min"] == {
        "type": "number",
        "minimum": -20,
        "maximum": 20,
    }
    assert "math" in cast(list[str], fresh["required"])


@pytest.mark.parametrize(
    ("visual", "required"),
    [
        ("equation", {"equations"}),
        ("graph", {"expression", "x_min", "x_max", "y_min", "y_max"}),
        ("geometry", {"a", "b"}),
        ("calculus", {"expression", "x_min", "x_max", "y_min", "y_max", "operation"}),
        ("vectors", {"ax", "ay", "bx", "by"}),
    ],
)
def test_each_math_tool_has_a_complete_self_contained_generation_contract(
    visual: str, required: set[str]
) -> None:
    variant = _schema_variants(server.planning_schema("math", 30))[visual]
    fields = server.object_dict(variant["properties"])
    assert fields["visual"] == {"type": "string", "enum": [visual]}
    assert set(cast(list[str], variant["required"])) == {
        "title",
        "narration",
        "visual",
        "duration",
        "background",
        "accent",
        "math",
    }
    assert "composition" not in fields
    assert variant["additionalProperties"] is False
    contract = server.object_dict(fields["math"])
    assert contract["type"] == "object"
    assert set(cast(list[str], contract["required"])) == required
    assert set(server.object_dict(contract["properties"])) == required
    assert contract["additionalProperties"] is False


@pytest.mark.parametrize("visual", math_spec.MATH_VISUALS)
@pytest.mark.parametrize("missing", ["absent", "empty", "null"])
def test_generated_math_without_its_content_is_rejected_without_sample_substitution(
    visual: str, missing: str
) -> None:
    plan = _math_plan(1)
    scene = _scenes(plan)[0]
    scene["visual"] = visual
    if missing == "absent":
        scene.pop("math")
    else:
        scene["math"] = {} if missing == "empty" else None
    original = copy.deepcopy(plan)
    with pytest.raises(ValueError, match="invalid storyboard"):
        server.generated_plan(json.dumps(plan), "math", 12)
    assert plan == original


@pytest.mark.parametrize(
    ("visual", "missing"),
    [
        (visual, field)
        for visual in math_spec.MATH_VISUALS
        for field in math_parameters(visual)
    ],
)
def test_generated_math_rejects_each_missing_required_tool_value(
    visual: str, missing: str
) -> None:
    plan = _math_plan(1)
    scene = _scenes(plan)[0]
    parameters = math_parameters(visual)
    parameters.pop(missing)
    scene.update(visual=visual, math=parameters)
    original = copy.deepcopy(plan)
    with pytest.raises(ValueError, match="requires.*" + missing):
        server.generated_plan(json.dumps(plan), "math", 12)
    assert plan == original


def test_local_ollama_planning_preserves_math_and_authored_timing() -> None:
    generated = _math_plan()
    ollama = server.Ollama()
    with patch.object(
        ollama,
        "request",
        side_effect=[
            {"models": [{"name": "local:3b"}]},
            {"response": json.dumps(generated)},
        ],
    ) as request:
        result = ollama.plan(
            "Plot the shifted square function.", "local:3b", "math", 12
        )
    assert result["mode"] == "math"
    assert [scene["duration"] for scene in _scenes(result)] == [3, 4]
    assert _scenes(result)[0]["math"] == _scenes(generated)[0]["math"]
    path, payload = request.call_args_list[1].args
    assert path == "/api/generate"
    assert payload["format"] == server.planning_schema("math", 12)
    assert payload["keep_alive"] == 0


def test_model_cannot_smuggle_unsafe_math_into_a_storyboard() -> None:
    plan = _math_plan()
    server.object_dict(_scenes(plan)[0]["math"])["expression"] = "x.__class__"
    ollama = server.Ollama()
    with (
        patch.object(
            ollama,
            "request",
            side_effect=[
                {"models": [{"name": "local:3b"}]},
                {"response": json.dumps(plan)},
            ],
        ),
        pytest.raises(ValueError, match="invalid storyboard"),
    ):
        ollama.plan("A graph", "local:3b", "math", 12)


def test_math_request_queues_and_persists_an_editable_plan(
    application: server.Application,
) -> None:
    plan = server.validate_plan(_math_plan())
    with patch.object(application.ollama, "plan", return_value=plan) as planner:
        job = application.submit_plan(
            {
                "prompt": "A parabola",
                "model": "local:3b",
                "mode": "math",
                "duration": 12,
            }
        )
        application.executor.submit(lambda: None).result(timeout=5)
    planner.assert_called_once_with("A parabola", "local:3b", "math", 12.0)
    assert job.snapshot()["status"] == "complete"
    assert job.snapshot()["plan"] == plan
    saved = application.directory / job.id / "plan.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == plan


def test_math_render_receives_parameters_and_publishes_the_saved_plan(
    application: server.Application,
) -> None:
    plan = _math_plan()
    with patch.object(renderer, "render_project") as render:
        job = application.submit_render(
            {"plan": plan, "voice_enabled": False, "music_enabled": False}
        )
        application.executor.submit(lambda: None).result(timeout=5)
    assert job.snapshot()["status"] == "complete"
    rendered_plan, directory, options, _progress = render.call_args.args
    assert rendered_plan == server.validate_plan(plan)
    assert not options["voice_enabled"]
    assert not options["music_enabled"]
    assert (
        json.loads((directory / "plan.json").read_text(encoding="utf-8"))
        == rendered_plan
    )
    assert job.snapshot()["video_url"] == f"/media/{job.id}/project.mp4"


def test_invalid_math_is_rejected_before_render_enters_the_worker_queue(
    application: server.Application,
) -> None:
    plan = _math_plan()
    server.object_dict(_scenes(plan)[0]["math"])["expression"] = "1/x"
    with (
        patch.object(application.executor, "submit") as submit,
        pytest.raises(ValueError, match="Function"),
    ):
        application.submit_render({"plan": plan})
    submit.assert_not_called()
    assert application.jobs == {}
