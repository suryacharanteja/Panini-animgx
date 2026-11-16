# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
# These tests deliberately use stdlib unittest so Studio needs no test dependencies.
# ruff: noqa: PT009, PT027
"""Exercise Studio's data boundaries, workers, and real loopback HTTP server."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from collections.abc import Callable
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from typing import cast
from unittest.mock import patch
from urllib.error import URLError

from studio import math_spec, renderer, server


def example_plan() -> dict[str, object]:
    """Return a fresh plan so boundary tests do not share mutable data."""
    return {
        "title": "A local film",
        "mode": "explainer",
        "scenes": [
            {
                "title": "Our first scene",
                "narration": "Small ideas can grow into something wonderful.",
                "visual": "composition",
                "composition": {
                    "elements": [
                        {
                            "kind": "text",
                            "text": "An idea grows",
                            "start": 0,
                            "end": 0.3,
                            "x": 0,
                            "y": 1,
                            "entrance": "write",
                        },
                        {
                            "kind": "circle",
                            "radius": 0.7,
                            "start": 0.3,
                            "end": 0.5,
                            "x": -2,
                            "y": 0,
                            "motion": {"start": 0.5, "end": 0.9, "x": 2, "y": 0},
                        },
                    ]
                },
                "duration": 6,
                "background": "#112233",
                "accent": "#ABCDEF",
            }
        ],
    }


def first_scene(plan: dict[str, object]) -> dict[str, object]:
    """Access the single scene in a test fixture."""
    return cast(list[dict[str, object]], plan["scenes"])[0]


def generated_plan(count: int, mode: str) -> dict[str, object]:
    """Make realistic model output with the requested style and varied durations."""
    plan = example_plan()
    plan["mode"] = mode
    scenes: list[dict[str, object]] = []
    for index in range(count):
        scene = first_scene(example_plan())
        scene["visual"] = "composition"
        scene["composition"] = {
            "elements": [
                {
                    "kind": "text",
                    "text": f"An original {mode} scene {index + 1}",
                    "start": 0,
                    "end": 0.3,
                    "x": 0,
                    "y": 1,
                    "entrance": "write",
                },
                {
                    "kind": "circle",
                    "radius": 0.5 + index / 10,
                    "start": 0.3,
                    "end": 0.5,
                    "x": -2,
                    "y": 0,
                    "motion": {"start": 0.5, "end": 0.9, "x": 2, "y": 0},
                },
            ]
        }
        scene["duration"] = 3 + index
        scenes.append(scene)
    plan["scenes"] = scenes
    return plan


def math_parameters(visual: str) -> dict[str, object]:
    """Provide explicit content for mathematical rendering capabilities."""
    if visual == "equation":
        return {"equations": ["y=x^3", "y'=3x^2"]}
    if visual in ("graph", "calculus"):
        parameters: dict[str, object] = {
            "expression": "sin(x)",
            "x_min": -3,
            "x_max": 3,
            "y_min": -2,
            "y_max": 2,
        }
        if visual == "calculus":
            parameters["operation"] = "derivative"
        return parameters
    if visual == "geometry":
        return {"a": 2.5, "b": 5}
    return {"ax": 1, "ay": -2, "bx": -3, "by": 1}


class ValidatePlanTests(unittest.TestCase):
    """Reject unsafe dimensions without treating story text as executable code."""

    def test_normalizes_allowed_fields_without_mutating_input(self) -> None:
        plan = example_plan()
        plan["title"] = "  My film  "
        plan["command"] = "ignored"
        first_scene(plan)["title"] = "  First scene  "
        first_scene(plan)["narration"] = "  A spoken line.  "
        first_scene(plan)["python"] = "ignored"
        result = server.validate_plan(plan)
        self.assertEqual(result["title"], "My film")
        self.assertEqual(first_scene(result)["title"], "First scene")
        self.assertEqual(first_scene(result)["narration"], "A spoken line.")
        self.assertIsInstance(first_scene(result)["duration"], float)
        self.assertNotIn("command", result)
        self.assertNotIn("python", first_scene(result))
        self.assertEqual(plan["title"], "  My film  ")

    def test_script_and_shell_text_remain_story_data(self) -> None:
        plan = example_plan()
        text = '<script>alert("story")</script> $(echo story) __import__("os")'
        plan["title"] = text
        first_scene(plan)["title"] = text
        first_scene(plan)["narration"] = text
        result = server.validate_plan(plan)
        self.assertEqual(result["title"], text)
        self.assertEqual(first_scene(result)["title"], text)
        self.assertEqual(first_scene(result)["narration"], text)

    def test_supports_explicit_math_and_authored_composition_content(
        self,
    ) -> None:
        for mode in ("math", "anime", "explainer"):
            for visual in (*math_spec.MATH_VISUALS, "composition"):
                with self.subTest(mode=mode, visual=visual):
                    plan = example_plan()
                    plan["mode"] = mode
                    first_scene(plan)["visual"] = visual
                    if visual in math_spec.MATH_VISUALS:
                        first_scene(plan)["math"] = math_parameters(visual)
                    elif visual == "composition":
                        first_scene(plan)["composition"] = first_scene(
                            generated_plan(1, mode)
                        )["composition"]
                    result = server.validate_plan(plan)
                    self.assertEqual(result["mode"], mode)
                    self.assertEqual(first_scene(result)["visual"], visual)

    def test_retired_presets_require_a_new_authored_storyboard(self) -> None:
        for mode in ("math", "anime", "explainer"):
            for visual in ("orbit", "process", "bars", "character", "landscape"):
                with self.subTest(mode=mode, visual=visual):
                    plan = example_plan()
                    plan["mode"] = mode
                    first_scene(plan)["visual"] = visual
                    first_scene(plan).pop("composition")
                    with self.assertRaisesRegex(ValueError, "Create a new storyboard"):
                        server.validate_plan(plan)

    def test_model_retired_presets_are_rejected_without_replacement(self) -> None:
        for visual in ("orbit", "process", "bars", "character", "landscape"):
            with self.subTest(visual=visual):
                plan = example_plan()
                first_scene(plan)["visual"] = visual
                first_scene(plan).pop("composition")
                original = json.dumps(plan, sort_keys=True)
                with self.assertRaisesRegex(ValueError, "Create a new storyboard"):
                    server.generated_plan(json.dumps(plan), "explainer", 12)
                self.assertEqual(json.dumps(plan, sort_keys=True), original)

    def test_rejects_non_objects_and_missing_fields(self) -> None:
        for value in (None, [], "plan", 1, True, {}, {"title": "Film"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.validate_plan(value)

    def test_scene_duration_is_finite_bounded_and_not_boolean(self) -> None:
        for duration in (
            None,
            True,
            "6",
            2.99,
            20.01,
            float("nan"),
            float("inf"),
            -float("inf"),
            10**1000,
        ):
            with self.subTest(duration=duration):
                plan = example_plan()
                first_scene(plan)["duration"] = duration
                with self.assertRaises(ValueError):
                    server.validate_plan(plan)
        for duration in (3, 20):
            plan = example_plan()
            first_scene(plan)["duration"] = duration
            self.assertEqual(
                first_scene(server.validate_plan(plan))["duration"], duration
            )

    def test_bounds_scene_count_and_total_duration(self) -> None:
        for count in (0, 9):
            plan = example_plan()
            plan["scenes"] = [first_scene(example_plan()) for _ in range(count)]
            with self.subTest(count=count), self.assertRaises(ValueError):
                server.validate_plan(plan)
        plan = example_plan()
        scene = first_scene(plan)
        scene["duration"] = 20
        plan["scenes"] = [scene.copy() for _ in range(6)]
        self.assertEqual(
            len(cast(list[object], server.validate_plan(plan)["scenes"])), 6
        )
        plan["scenes"] = [scene.copy() for _ in range(7)]
        with self.assertRaisesRegex(ValueError, "120 seconds"):
            server.validate_plan(plan)

    def test_rejects_unknown_visuals_and_unbounded_text(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("visual", "execute_python"),
            ("visual", {"code": "arbitrary"}),
            ("title", ""),
            ("title", "x" * 101),
            ("title", "Caption\x00"),
            ("narration", "x" * 601),
            ("narration", "Narration\x1b"),
            ("narration", []),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                plan = example_plan()
                first_scene(plan)[field] = value
                with self.assertRaises(ValueError):
                    server.validate_plan(plan)
        for title in ("", "x" * 121, "Title\x00"):
            plan = example_plan()
            plan["title"] = title
            with self.subTest(title=title), self.assertRaises(ValueError):
                server.validate_plan(plan)

    def test_accepts_empty_narration_and_rejects_invalid_colors(self) -> None:
        plan = example_plan()
        first_scene(plan)["narration"] = ""
        self.assertEqual(first_scene(server.validate_plan(plan))["narration"], "")
        for key in ("background", "accent"):
            for color in ("red", "#abc", "#1234567", "#12345G", None):
                with self.subTest(key=key, color=color):
                    plan = example_plan()
                    first_scene(plan)[key] = color
                    with self.assertRaises(ValueError):
                        server.validate_plan(plan)


class RenderOptionsTests(unittest.TestCase):
    """Keep local narration and soundtrack requests within export limits."""

    def test_defaults_and_explicit_disabled_audio(self) -> None:
        self.assertEqual(
            server.render_options({}),
            {
                "voice_enabled": True,
                "music_enabled": True,
                "voice": "",
                "music_volume": 0.12,
                "quality": "preview",
            },
        )
        self.assertEqual(
            server.render_options(
                {
                    "voice_enabled": False,
                    "music_enabled": False,
                    "voice": "Local voice",
                    "quality": "final",
                    "music_volume": 0.3,
                }
            ),
            {
                "voice_enabled": False,
                "music_enabled": False,
                "voice": "Local voice",
                "quality": "final",
                "music_volume": 0.3,
            },
        )

    def test_rejects_invalid_audio_and_quality_settings(self) -> None:
        invalid: tuple[tuple[str, object], ...] = (
            ("voice_enabled", "false"),
            ("voice_enabled", 1),
            ("music_enabled", 0),
            ("voice", 1),
            ("voice", "x" * 201),
            ("quality", "ultra"),
            ("music_volume", True),
            ("music_volume", -0.01),
            ("music_volume", 0.31),
            ("music_volume", float("nan")),
            ("music_volume", float("inf")),
            ("music_volume", 10**1000),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                server.render_options({key: value})


class PlanningSchemaTests(unittest.TestCase):
    """Constrain capabilities while letting the model author scene count and pacing."""

    def test_schema_limits_style_mode_and_scene_count(self) -> None:
        for mode, visuals in (
            ("anime", ["composition"]),
            ("explainer", ["composition"]),
        ):
            for duration, maximum_scenes in ((6, 2), (30, 8), (120, 8)):
                with self.subTest(mode=mode, duration=duration):
                    properties = server.object_dict(
                        server.planning_schema(mode, duration)["properties"]
                    )
                    self.assertEqual(
                        properties["mode"], {"type": "string", "enum": [mode]}
                    )
                    scenes = server.object_dict(properties["scenes"])
                    self.assertEqual(
                        (scenes["minItems"], scenes["maxItems"]), (1, maximum_scenes)
                    )
                    variants = cast(
                        list[dict[str, object]],
                        server.object_dict(scenes["items"])["anyOf"],
                    )
                    self.assertEqual(len(variants), 1)
                    item = variants[0]
                    fields = server.object_dict(item["properties"])
                    self.assertEqual(
                        fields["visual"], {"type": "string", "enum": visuals}
                    )
                    self.assertIn(
                        "composition",
                        cast(list[str], item["required"]),
                    )
                    self.assertNotIn("math", fields)
                    self.assertFalse(item["additionalProperties"])

    def test_schema_copies_do_not_mutate_global_or_other_requests(self) -> None:
        original = json.dumps(server.PLAN_SCHEMA, sort_keys=True)
        anime = server.planning_schema("anime", 30)
        properties = server.object_dict(anime["properties"])
        scenes = server.object_dict(properties["scenes"])
        variants = cast(
            list[dict[str, object]], server.object_dict(scenes["items"])["anyOf"]
        )
        fields = server.object_dict(variants[0]["properties"])
        fields["visual"] = {"type": "string", "enum": ["injected"]}
        scenes["maxItems"] = 999
        following = server.object_dict(
            server.planning_schema("anime", 30)["properties"]
        )
        self.assertEqual(server.object_dict(following["scenes"])["maxItems"], 8)
        self.assertNotEqual(anime, server.planning_schema("anime", 30))
        self.assertEqual(json.dumps(server.PLAN_SCHEMA, sort_keys=True), original)


class DynamicGenerationTests(unittest.TestCase):
    """Preserve authored video and soundtrack data through provider validation."""

    def test_authored_composition_and_music_are_retained_without_substitutions(
        self,
    ) -> None:
        generated = generated_plan(3, "explainer")
        generated["music"] = {"tempo": 83.5, "chords": [[43, 50], [46, 53, 58]]}
        original = json.dumps(generated, sort_keys=True)
        result = server.generated_plan(json.dumps(generated), "explainer", 90)
        self.assertEqual(result["music"], generated["music"])
        self.assertEqual(
            [
                scene["composition"]
                for scene in cast(list[dict[str, object]], result["scenes"])
            ],
            [
                scene["composition"]
                for scene in cast(list[dict[str, object]], generated["scenes"])
            ],
        )
        self.assertEqual(
            [
                scene["duration"]
                for scene in cast(list[dict[str, object]], result["scenes"])
            ],
            [3, 4, 5],
        )
        self.assertEqual(json.dumps(generated, sort_keys=True), original)

    def test_selected_mode_is_applied_before_reviewing_math_capabilities(self) -> None:
        generated = example_plan()
        first_scene(generated).update(visual="graph", math=math_parameters("graph"))
        result = server.generated_plan(json.dumps(generated), "math", 12)
        self.assertEqual(result["mode"], "math")
        self.assertEqual(first_scene(result)["math"], math_parameters("graph"))

    def test_math_mode_accepts_authored_compositions(self) -> None:
        generated = generated_plan(1, "anime")
        result = server.generated_plan(json.dumps(generated), "math", 12)
        self.assertEqual(result["mode"], "math")
        self.assertEqual(
            first_scene(result)["composition"], first_scene(generated)["composition"]
        )

    def test_invalid_composition_fails_without_replacing_its_content(self) -> None:
        invalid: tuple[object, ...] = (
            None,
            {"elements": []},
            {"elements": [{"kind": "text", "start": 0, "end": 0.2}]},
            {"elements": [{"kind": "python", "start": 0, "end": 0.2}]},
            {"elements": [{"kind": "circle", "radius": 50, "start": 0, "end": 0.2}]},
            {"elements": [{"kind": "text", "text": "Topic", "start": 0.8, "end": 0.2}]},
        )
        for composition in invalid:
            generated = generated_plan(1, "anime")
            first_scene(generated)["composition"] = composition
            with (
                self.subTest(composition=composition),
                self.assertRaisesRegex(ValueError, "invalid storyboard"),
            ):
                server.generated_plan(json.dumps(generated), "anime", 30)

    def test_invalid_soundtrack_fails_without_substituting_a_progression(self) -> None:
        for music in (
            None,
            {"tempo": 72, "chords": []},
            {"tempo": 181, "chords": [[48]]},
            {"tempo": 72, "chords": [[85]]},
            {"tempo": 72, "chords": [[48]], "url": "https://music.example/song.mp3"},
        ):
            generated = generated_plan(1, "explainer")
            generated["music"] = music
            with (
                self.subTest(music=music),
                self.assertRaisesRegex(ValueError, "invalid storyboard"),
            ):
                server.generated_plan(json.dumps(generated), "explainer", 30)


class OllamaTests(unittest.TestCase):
    """Validate model selection and output without downloading or loading a model."""

    def test_generation_uses_schema_and_overrides_model_mode(self) -> None:
        ollama = server.Ollama()
        generated = generated_plan(2, "anime")
        generated["mode"] = "explainer"
        responses = [
            {"models": [{"name": "local:3b"}]},
            {"response": json.dumps(generated)},
        ]
        with patch.object(ollama, "request", side_effect=responses) as request:
            result = ollama.plan(
                "A character explores a valley.", "local:3b", "anime", 12
            )
        self.assertEqual(result["mode"], "anime")
        path, payload = request.call_args_list[1].args
        self.assertEqual(path, "/api/generate")
        self.assertEqual(payload["model"], "local:3b")
        self.assertEqual(payload["format"], server.planning_schema("anime", 12))
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["keep_alive"], 0)
        grounded_schema = json.loads(payload["prompt"].split("\n")[-1])
        self.assertEqual(grounded_schema, payload["format"])
        self.assertIn("A character explores a valley.", payload["prompt"])
        self.assertEqual(payload["options"]["temperature"], 0)

    def test_rejects_output_that_ignores_requested_style(self) -> None:
        for mode, wrong_visual in (("anime", "graph"), ("explainer", "equation")):
            with self.subTest(mode=mode):
                generated = generated_plan(2, mode)
                first_scene(generated)["visual"] = wrong_visual
                first_scene(generated)["math"] = math_parameters(wrong_visual)
                ollama = server.Ollama()
                with (
                    patch.object(
                        ollama,
                        "request",
                        side_effect=[
                            {"models": [{"name": "local:3b"}]},
                            {"response": json.dumps(generated)},
                        ],
                    ),
                    self.assertRaisesRegex(ValueError, "requested scene style"),
                ):
                    ollama.plan("Film", "local:3b", mode, 12)

    def test_model_can_choose_any_bounded_scene_count(self) -> None:
        for count in (1, 3, 8):
            with self.subTest(count=count):
                ollama = server.Ollama()
                with (
                    patch.object(
                        ollama,
                        "request",
                        side_effect=[
                            {"models": [{"name": "local:3b"}]},
                            {"response": json.dumps(generated_plan(count, "anime"))},
                        ],
                    ),
                ):
                    result = ollama.plan("Film", "local:3b", "anime", 12)
                self.assertEqual(len(cast(list[object], result["scenes"])), count)

    def test_preserves_model_scene_durations_without_forcing_target_total(self) -> None:
        for mode in ("anime", "explainer"):
            for duration, count in ((6, 2), (30, 3), (120, 6)):
                with self.subTest(mode=mode, duration=duration):
                    ollama = server.Ollama()
                    with patch.object(
                        ollama,
                        "request",
                        side_effect=[
                            {"models": [{"name": "local:3b"}]},
                            {"response": json.dumps(generated_plan(count, mode))},
                        ],
                    ):
                        result = ollama.plan("Film", "local:3b", mode, duration)
                    scenes = cast(list[dict[str, object]], result["scenes"])
                    self.assertEqual(
                        [scene["duration"] for scene in scenes],
                        [3 + index for index in range(count)],
                    )
                    self.assertEqual(
                        sum(cast(float, scene["duration"]) for scene in scenes),
                        sum(3 + index for index in range(count)),
                    )
                    self.assertEqual(server.validate_plan(result), result)

    def test_rejects_absent_model_before_generation(self) -> None:
        ollama = server.Ollama()
        with (
            patch.object(ollama, "request", return_value={"models": []}) as request,
            self.assertRaisesRegex(ValueError, "not installed"),
        ):
            ollama.plan("A film", "missing:3b", "anime", 12)
        request.assert_called_once_with("/api/tags")

    def test_invalid_model_output_is_a_useful_error(self) -> None:
        for response in (None, "not json", "[]", '{"title": "Film"}'):
            with self.subTest(response=response):
                ollama = server.Ollama()
                with (
                    patch.object(
                        ollama,
                        "request",
                        side_effect=[
                            {"models": [{"name": "local:3b"}]},
                            {"response": response},
                        ],
                    ),
                    self.assertRaisesRegex(ValueError, "storyboard"),
                ):
                    ollama.plan("A film", "local:3b", "anime", 12)

    def test_transport_error_explains_how_to_reconnect(self) -> None:
        with (
            patch.object(server, "urlopen", side_effect=URLError("refused")),
            self.assertRaisesRegex(ValueError, "Start Ollama"),
        ):
            server.Ollama().models()


class ApplicationTests(unittest.TestCase):
    """Verify queued work, persisted plans, and reported renderer failures."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parent
        )
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.application = server.Application(self.directory)
        self.addCleanup(
            self.application.executor.shutdown, wait=True, cancel_futures=True
        )

    def finish_jobs(self) -> None:
        """Fence queued worker tasks while leaving the executor usable."""
        self.application.executor.submit(lambda: None).result(timeout=5)

    def test_plan_job_persists_model_result(self) -> None:
        plan = example_plan()
        with patch.object(
            self.application.ollama, "plan", return_value=plan
        ) as planner:
            job = self.application.submit_plan(
                {
                    "prompt": "  A brief  ",
                    "model": "local:3b",
                    "mode": "explainer",
                    "duration": 12,
                }
            )
            self.finish_jobs()
        planner.assert_called_once_with("A brief", "local:3b", "explainer", 12.0)
        snapshot = self.application.get_job(job.id)
        self.assertIsNotNone(snapshot)
        self.assertEqual(cast(dict[str, object], snapshot)["status"], "complete")
        self.assertEqual(cast(dict[str, object], snapshot)["plan"], plan)
        saved = self.directory / job.id / "plan.json"
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), plan)
        self.assertIsNone(self.application.get_job("missing"))

    def test_render_receives_validated_data_and_publishes_video_url(self) -> None:
        def render(
            plan: dict[str, object],
            directory: Path,
            options: dict[str, object],
            progress: Callable[[str], None],
        ) -> None:
            self.assertEqual(plan, server.validate_plan(example_plan()))
            self.assertFalse(options["voice_enabled"])
            self.assertFalse(options["music_enabled"])
            progress("Finishing the film.")
            (directory / "project.mp4").write_bytes(b"local film")

        with patch.object(
            renderer, "render_project", side_effect=render
        ) as render_project:
            job = self.application.submit_render(
                {
                    "plan": example_plan(),
                    "voice_enabled": False,
                    "music_enabled": False,
                }
            )
            self.finish_jobs()
        render_project.assert_called_once()
        snapshot = job.snapshot()
        self.assertEqual(snapshot["status"], "complete")
        self.assertEqual(snapshot["video_url"], f"/media/{job.id}/project.mp4")
        self.assertIsNone(snapshot["error"])
        self.assertTrue((self.directory / job.id / "plan.json").is_file())

    def test_worker_failures_remain_pollable(self) -> None:
        with patch.object(
            self.application.ollama, "plan", side_effect=ValueError("Model unavailable")
        ):
            planning = self.application.submit_plan(
                {
                    "prompt": "Film",
                    "model": "local:3b",
                    "mode": "anime",
                }
            )
            self.finish_jobs()
        self.assertEqual(planning.snapshot()["status"], "failed")
        self.assertEqual(planning.snapshot()["error"], "Model unavailable")
        with patch.object(
            renderer, "render_project", side_effect=RuntimeError("GPU unavailable")
        ):
            rendering = self.application.submit_render({"plan": example_plan()})
            self.finish_jobs()
        self.assertEqual(rendering.snapshot()["status"], "failed")
        self.assertEqual(rendering.snapshot()["error"], "GPU unavailable")
        self.assertIsNone(rendering.snapshot()["video_url"])
        self.assertEqual(
            rendering.snapshot()["plan"], server.validate_plan(example_plan())
        )

    def test_invalid_request_never_enters_queue(self) -> None:
        with patch.object(self.application.executor, "submit") as submit:
            with self.assertRaises(ValueError):
                self.application.submit_render({"plan": None})
            with self.assertRaises(ValueError):
                self.application.submit_plan(
                    {
                        "prompt": "Film",
                        "model": "local:3b",
                        "mode": "anime",
                        "duration": float("nan"),
                    }
                )
        submit.assert_not_called()
        self.assertEqual(self.application.jobs, {})

    def test_bounded_queue_rejects_fifth_active_job(self) -> None:
        brief: dict[str, object] = {
            "prompt": "Film",
            "model": "local:3b",
            "mode": "anime",
        }
        with patch.object(self.application.executor, "submit") as submit:
            for _ in range(4):
                self.application.submit_plan(brief)
            with self.assertRaisesRegex(ValueError, "queue is full"):
                self.application.submit_plan(brief)
        self.assertEqual(submit.call_count, 4)
        self.assertEqual(len(self.application.jobs), 4)

    def test_status_reports_disconnected_ollama_without_requiring_gpu(self) -> None:
        with (
            patch.object(
                self.application.ollama,
                "models",
                side_effect=ValueError("Start Ollama"),
            ),
            patch.object(renderer, "engine_status", return_value={"available": False}),
            patch.object(renderer, "get_voices", return_value=[]),
        ):
            status = self.application.status()
        self.assertEqual(
            status["ollama"],
            {"connected": False, "models": [], "error": "Start Ollama"},
        )
        self.assertEqual(status["voices"], [])


class HttpTests(unittest.TestCase):
    """Send requests through sockets to verify HTTP boundaries and media seeking."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        web = self.root / "web"
        web.mkdir()
        (web / "index.html").write_text(
            "<!doctype html><title>Studio test</title>", encoding="utf-8"
        )
        (web / "app.js").write_text("console.log('studio');", encoding="utf-8")
        (web / "styles.css").write_text("body { color: blue; }", encoding="utf-8")
        branding = web / "assets" / "branding"
        branding.mkdir(parents=True)
        for name in server.BRANDING_FILES:
            source = server.ROOT / "web" / "assets" / "branding" / name
            (branding / name).write_bytes(source.read_bytes())
        self.application = server.Application(self.root / "data")
        self.addCleanup(
            self.application.executor.shutdown, wait=True, cancel_futures=True
        )
        patches = (
            patch.object(server, "ROOT", self.root),
            patch.object(server.Handler, "log_message"),
            patch.object(self.application.ollama, "models", return_value=["local:3b"]),
            patch.object(renderer, "engine_status", return_value={"available": True}),
            patch.object(renderer, "get_voices", return_value=[]),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        try:
            self.http_server = server.StudioServer(("127.0.0.1", 0), self.application)
        except PermissionError as error:
            self.skipTest(f"The sandbox blocks loopback sockets: {error}")
        self.addCleanup(self.http_server.server_close)
        self.thread = threading.Thread(
            target=self.http_server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.http_server.shutdown)
        self.host = f"127.0.0.1:{self.http_server.server_port}"
        probe = HTTPConnection("127.0.0.1", self.http_server.server_port, timeout=5)
        try:
            probe.connect()
        except PermissionError as error:
            self.skipTest(f"The sandbox blocks loopback connections: {error}")
        finally:
            probe.close()
        self.media_id = "a" * 32
        media = self.application.directory / self.media_id
        media.mkdir(parents=True)
        self.video = bytes(range(100))
        (media / "project.mp4").write_bytes(self.video)

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        """Read one real HTTP response with a bounded timeout."""
        connection = HTTPConnection(
            "127.0.0.1", self.http_server.server_port, timeout=5
        )
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_a_live_preview_port_cannot_be_bound_by_another_server(self) -> None:
        with (
            self.assertRaises(OSError),
            server.StudioServer(
                ("127.0.0.1", self.http_server.server_port), self.application
            ),
        ):
            pass

    def test_static_assets_and_real_status_endpoint(self) -> None:
        for path, mime in (
            ("/", "text/html"),
            ("/app.js", "javascript"),
            ("/styles.css", "text/css"),
        ):
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, HTTPStatus.OK)
                self.assertIn(mime, headers["Content-Type"])
                self.assertTrue(body)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertIn(
                    "frame-ancestors 'none'", headers["Content-Security-Policy"]
                )
        status, _, body = self.request("GET", "/api/status")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(json.loads(body)["ollama"]["models"], ["local:3b"])

    def test_runtime_endpoint_reports_protocol_and_restart_state(self) -> None:
        status, headers, body = self.request("GET", "/api/runtime")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(json.loads(body), {"protocol": 2, "restart_required": False})

    def test_supplied_brand_assets_are_served_with_image_metadata(self) -> None:
        expected = {
            "panini-animgx-lockup.png",
            "panini-animgx-icon.svg",
            "panini-animgx-icon-32.png",
            "panini-animgx-icon-64.png",
            "panini-animgx-icon-128.png",
        }
        self.assertEqual(server.BRANDING_FILES, expected)
        for name in expected:
            with self.subTest(name=name):
                status, headers, body = self.request("GET", f"/assets/branding/{name}")
                self.assertEqual(status, HTTPStatus.OK)
                self.assertIn(
                    "image/svg+xml" if name.endswith(".svg") else "image/png",
                    headers["Content-Type"],
                )
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(
                    body,
                    (self.root / "web" / "assets" / "branding" / name).read_bytes(),
                )

    def test_branding_allowlist_rejects_unlisted_files_and_traversal(self) -> None:
        secret = self.root / "web" / "assets" / "branding" / "private.png"
        secret.write_bytes(b"not public artwork")
        for path in (
            "/assets/branding/private.png",
            "/assets/branding/unknown.svg",
            "/assets/branding/panini-animgx-icon-256.png",
            "/assets/branding/../index.html",
            "/assets/branding/%2e%2e/index.html",
            "/assets/branding/%2e%2e%2f%2e%2e%2fapp.js",
            "/assets/branding/nested/panini-animgx-icon.svg",
        ):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, HTTPStatus.NOT_FOUND)
                self.assertNotIn(b"not public artwork", body)

    def test_bad_host_or_origin_rejected_for_get_and_post(self) -> None:
        for headers in (
            {"Host": "attacker.example"},
            {"Host": f"attacker.example:{self.http_server.server_port}"},
            {"Origin": "https://attacker.example"},
            {"Origin": "null"},
        ):
            for method in ("GET", "POST"):
                with self.subTest(headers=headers, method=method):
                    status, _, _ = self.request(method, "/api/status", headers=headers)
                    self.assertEqual(status, HTTPStatus.FORBIDDEN)
        status, _, _ = self.request(
            "GET", "/api/status", headers={"Origin": f"http://{self.host}"}
        )
        self.assertEqual(status, HTTPStatus.OK)

    def test_request_types_size_and_json_errors_rejected(self) -> None:
        cases: tuple[tuple[bytes, dict[str, str], HTTPStatus], ...] = (
            (b"{}", {"Content-Type": "text/plain"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
            (b"not json", {"Content-Type": "application/json"}, HTTPStatus.BAD_REQUEST),
            (b"[]", {"Content-Type": "application/json"}, HTTPStatus.BAD_REQUEST),
            (b"\xff", {"Content-Type": "application/json"}, HTTPStatus.BAD_REQUEST),
            (
                b"",
                {"Content-Type": "application/json"},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            ),
            (
                b"{}",
                {
                    "Content-Type": "application/json",
                    "Content-Length": str(server.MAX_BODY + 1),
                },
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            ),
            (
                b"{}",
                {"Content-Type": "application/json", "Content-Length": "invalid"},
                HTTPStatus.BAD_REQUEST,
            ),
        )
        for body, headers, expected in cases:
            with self.subTest(headers=headers, body=body):
                status, _, _ = self.request("POST", "/api/plan", body, headers)
                self.assertEqual(status, expected)
        self.assertEqual(self.application.jobs, {})

    def test_unknown_routes_and_traversal_cannot_read_files(self) -> None:
        (self.root / "secret.txt").write_text("not an asset", encoding="utf-8")
        for path in (
            "/secret.txt",
            "/../secret.txt",
            "/%2e%2e/secret.txt",
            f"/media/{self.media_id}/../secret.txt",
            "/api/jobs/missing",
            "/media/invalid/project.mp4",
        ):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, HTTPStatus.NOT_FOUND)
                self.assertNotIn(b"not an asset", body)

    def test_oversized_rejection_finishes_without_waiting_for_full_upload(self) -> None:
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(server.MAX_BODY + 1),
        }
        # A client may send no body after seeing a rejection, an incomplete body,
        # or the entire oversized upload. None should schedule work or lose 413.
        for body in (b"", b"{}", b"x" * (server.MAX_BODY + 1)):
            with self.subTest(uploaded_bytes=len(body)):
                status, _, response = self.request("POST", "/api/plan", body, headers)
                self.assertEqual(status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                self.assertEqual(
                    json.loads(response)["error"], "Request is empty or too large."
                )
        self.assertEqual(self.application.jobs, {})

    def test_rejected_split_uploads_do_not_reset_response(self) -> None:
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(server.MAX_BODY + 1),
        }
        # HTTPConnection sends the headers and these two body bytes separately.
        # Repeat to expose a close racing with the second write on Windows.
        for attempt in range(25):
            with self.subTest(attempt=attempt):
                status, _, response = self.request("POST", "/api/plan", b"{}", headers)
                self.assertEqual(status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                self.assertIn("error", json.loads(response))

    def test_plan_and_render_accepted_then_pollable(self) -> None:
        brief = {"prompt": "Film", "model": "local:3b", "mode": "explainer"}
        with patch.object(self.application.ollama, "plan", return_value=example_plan()):
            status, _, body = self.request(
                "POST",
                "/api/plan",
                json.dumps(brief).encode(),
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Origin": f"http://{self.host}",
                },
            )
            self.application.executor.submit(lambda: None).result(timeout=5)
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        plan_id = json.loads(body)["id"]
        status, _, body = self.request("GET", f"/api/jobs/{plan_id}")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(json.loads(body)["status"], "complete")
        with patch.object(renderer, "render_project"):
            status, _, body = self.request(
                "POST",
                "/api/render",
                json.dumps({"plan": example_plan()}).encode(),
                {"Content-Type": "application/json"},
            )
            self.application.executor.submit(lambda: None).result(timeout=5)
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        render_id = json.loads(body)["id"]
        status, _, body = self.request("GET", f"/api/jobs/{render_id}")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(
            json.loads(body)["video_url"], f"/media/{render_id}/project.mp4"
        )

    def test_mp4_full_and_byte_range_requests(self) -> None:
        path = f"/media/{self.media_id}/project.mp4"
        status, headers, body = self.request("GET", path)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["Content-Type"], "video/mp4")
        self.assertEqual(body, self.video)
        for byte_range, start, end in (
            ("bytes=10-19", 10, 19),
            ("bytes=90-", 90, 99),
            ("bytes=-7", 93, 99),
            ("bytes=0-999", 0, 99),
            ("bytes=-200", 0, 99),
        ):
            with self.subTest(byte_range=byte_range):
                status, headers, body = self.request(
                    "GET", path, headers={"Range": byte_range}
                )
                self.assertEqual(status, HTTPStatus.PARTIAL_CONTENT)
                self.assertEqual(headers["Content-Range"], f"bytes {start}-{end}/100")
                self.assertEqual(headers["Content-Length"], str(end - start + 1))
                self.assertEqual(body, self.video[start : end + 1])

    def test_invalid_byte_ranges_have_no_body(self) -> None:
        for byte_range in (
            "bytes=100-",
            "bytes=10-5",
            "bytes=-0",
            "bytes=-",
            "bytes=0-1,3-4",
            "items=1-3",
            "bytes=invalid",
        ):
            with self.subTest(byte_range=byte_range):
                status, headers, body = self.request(
                    "GET",
                    f"/media/{self.media_id}/project.mp4",
                    headers={"Range": byte_range},
                )
                self.assertEqual(status, HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.assertEqual(headers["Content-Range"], "bytes */100")
                self.assertEqual(body, b"")


if __name__ == "__main__":
    unittest.main()
