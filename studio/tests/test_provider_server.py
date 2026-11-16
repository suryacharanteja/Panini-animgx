# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
"""Cloud planners feed the same validated, local Manim rendering workflow."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from studio import renderer, server
from studio.tests.test_server import generated_plan

SECRET = "provider-route-test-secret-do-not-expose"


def _plan(count: int = 2) -> dict[str, object]:
    return {
        "title": "The derivative of a parabola",
        "mode": "math",
        "scenes": [
            {
                "title": f"A tangent {index + 1}",
                "narration": "The slope changes with x.",
                "visual": "calculus",
                "duration": 4,
                "background": "#102020",
                "accent": "#6CE5C0",
                "math": {
                    "expression": "x**2",
                    "x_min": -3,
                    "x_max": 3,
                    "y_min": -1,
                    "y_max": 9,
                    "operation": "derivative",
                },
            }
            for index in range(count)
        ],
    }


def _brief(provider: str | None = "openai") -> dict[str, object]:
    data: dict[str, object] = {
        "prompt": "Explain the derivative of x squared.",
        "model": "test-model",
        "mode": "math",
        "duration": 12,
    }
    if provider is not None:
        data["provider"] = provider
    return data


@pytest.fixture
def application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[server.Application]:
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "COMPATIBLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    application = server.Application(tmp_path / "data")
    try:
        yield application
    finally:
        application.executor.shutdown(wait=True, cancel_futures=True)


def _configured(application: server.Application, provider: str = "openai") -> None:
    data: dict[str, object] = {"provider": provider, "api_key": SECRET}
    if provider == "compatible":
        data["base_url"] = "https://models.example/v1"
        data["model"] = "test-model"
    application.update_settings(data)


@pytest.mark.parametrize("provider", ["openai", "gemini", "compatible"])
def test_cloud_planning_uses_math_schema_and_retains_validated_math(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    _configured(application, provider)
    calls: list[tuple[str, str, str, str, dict[str, object]]] = []

    def generate(
        provider: str, model: str, system: str, prompt: str, schema: dict[str, object]
    ) -> str:
        calls.append((provider, model, system, prompt, schema))
        return json.dumps(_plan())

    def unexpected_ollama(*args: object) -> None:
        pytest.fail("Cloud planning must not query or invoke the local model.")

    monkeypatch.setattr(application.planner, "generate", generate)
    monkeypatch.setattr(application.ollama, "models", unexpected_ollama)
    monkeypatch.setattr(application.ollama, "plan", unexpected_ollama)
    job = application.submit_plan(_brief(provider))
    application.executor.submit(lambda: None).result(timeout=5)
    assert len(calls) == 1
    assert calls[0][:2] == (provider, "test-model")
    assert "math" in calls[0][2]
    assert "Explain the derivative" in calls[0][3]
    assert calls[0][4] == server.planning_schema("math", 12)
    snapshot = job.snapshot()
    assert snapshot["status"] == "complete"
    assert snapshot["stage"] == "review"
    plan = cast(dict[str, object], snapshot["plan"])
    scenes = cast(list[dict[str, object]], plan["scenes"])
    assert len(scenes) == 2
    assert [scene["duration"] for scene in scenes] == [4, 4]
    assert cast(dict[str, object], scenes[0]["math"])["expression"] == "x**2"
    saved = application.directory / job.id / "plan.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == plan
    assert SECRET not in saved.read_text(encoding="utf-8")
    assert SECRET not in json.dumps(snapshot)


def test_active_provider_is_used_when_request_omits_provider(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured(application, "gemini")
    application.update_settings({"provider": "gemini", "active_provider": "gemini"})
    called: list[str] = []

    def generate(provider: str, *args: object) -> str:
        called.append(provider)
        return json.dumps(_plan())

    monkeypatch.setattr(application.planner, "generate", generate)
    job = application.submit_plan(_brief(None))
    application.executor.submit(lambda: None).result(timeout=5)
    assert called == ["gemini"]
    assert job.snapshot()["status"] == "complete"


@pytest.mark.parametrize("provider", ["openai", "gemini", "compatible"])
@pytest.mark.parametrize("count", [1, 3, 8])
def test_cloud_model_controls_scene_count_pacing_composition_and_score(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    count: int,
) -> None:
    _configured(application, provider)
    authored = generated_plan(count, "explainer")
    authored["music"] = {"tempo": 94, "chords": [[49, 56], [45, 52, 57]]}
    monkeypatch.setattr(
        application.planner, "generate", lambda *args: json.dumps(authored)
    )
    brief = _brief(provider)
    brief.update(mode="explainer", duration=90)
    job = application.submit_plan(brief)
    application.executor.submit(lambda: None).result(timeout=5)
    snapshot = job.snapshot()
    assert snapshot["status"] == "complete"
    result = cast(dict[str, object], snapshot["plan"])
    assert result["music"] == authored["music"]
    scenes = cast(list[dict[str, object]], result["scenes"])
    assert len(scenes) == count
    assert [scene["duration"] for scene in scenes] == list(range(3, 3 + count))
    assert [scene["composition"] for scene in scenes] == [
        scene["composition"]
        for scene in cast(list[dict[str, object]], authored["scenes"])
    ]
    saved = application.directory / job.id / "plan.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == result
    assert SECRET not in saved.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "provider", ["openai", "gemini", "compatible", "unknown", "", []]
)
def test_missing_credentials_or_unknown_provider_never_enters_queue(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
    provider: object,
) -> None:
    submissions: list[object] = []
    monkeypatch.setattr(
        application.executor, "submit", lambda *args: submissions.append(args)
    )
    data = _brief()
    data["provider"] = provider
    with pytest.raises(ValueError, match=r"Configure|Choose|Provider"):
        application.submit_plan(data)
    assert submissions == []
    assert application.jobs == {}


@pytest.mark.parametrize(
    "response",
    [
        "not JSON",
        json.dumps(_plan(0)),
        json.dumps({"title": "Incomplete"}),
    ],
)
def test_invalid_cloud_storyboards_fail_without_creating_renderable_output(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    _configured(application)
    monkeypatch.setattr(application.planner, "generate", lambda *args: response)
    job = application.submit_plan(_brief())
    application.executor.submit(lambda: None).result(timeout=5)
    snapshot = job.snapshot()
    assert snapshot["status"] == "failed"
    assert snapshot["stage"] == "failed"
    assert snapshot["plan"] is None
    assert SECRET not in json.dumps(snapshot)
    assert not (application.directory / job.id / "plan.json").exists()


def test_unsafe_math_from_cloud_is_rejected_before_local_render(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured(application)
    plan = _plan()
    scene = cast(list[dict[str, object]], plan["scenes"])[0]
    cast(dict[str, object], scene["math"])["expression"] = "__import__('os')"
    monkeypatch.setattr(application.planner, "generate", lambda *args: json.dumps(plan))
    job = application.submit_plan(_brief())
    application.executor.submit(lambda: None).result(timeout=5)
    assert job.snapshot()["status"] == "failed"
    assert job.snapshot()["plan"] is None


def test_settings_cannot_change_while_queued_or_running_jobs_use_them(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(application.executor, "submit", lambda *args: None)
    application.submit_plan(_brief("ollama"))
    original = application.settings.snapshot()
    with pytest.raises(ValueError, match="finish"):
        application.update_settings({"provider": "openai", "api_key": SECRET})
    assert application.settings.snapshot() == original


def test_provider_validation_and_queue_registration_share_one_lock(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second tab cannot change credentials between validation and submission."""
    _configured(application)
    original = application.settings.snapshot()
    validated = threading.Event()
    release = threading.Event()
    update_started = threading.Event()
    update_finished = threading.Event()
    provider_record = application.provider_record

    def paused_record(provider: str) -> dict[str, object]:
        record = provider_record(provider)
        validated.set()
        assert release.wait(5)
        return record

    def update_settings() -> None:
        update_started.set()
        try:
            application.update_settings({"provider": "openai", "clear_key": True})
        finally:
            update_finished.set()

    monkeypatch.setattr(application, "provider_record", paused_record)
    monkeypatch.setattr(application.executor, "submit", lambda *args: None)
    with ThreadPoolExecutor(max_workers=2) as callers:
        submission = callers.submit(application.submit_plan, _brief())
        try:
            assert validated.wait(5)
            update = callers.submit(update_settings)
            assert update_started.wait(5)
            assert not update_finished.wait(0.1)
        finally:
            release.set()
        assert submission.result(timeout=5).snapshot()["status"] == "queued"
        with pytest.raises(ValueError, match="finish"):
            update.result(timeout=5)
    assert application.settings.snapshot() == original


@pytest.mark.parametrize("kind", ["plan", "render"])
def test_stopped_executor_does_not_leave_a_phantom_queued_job(
    application: server.Application, kind: str
) -> None:
    application.executor.shutdown(wait=True)
    action = application.submit_plan if kind == "plan" else application.submit_render
    request = _brief("ollama") if kind == "plan" else {"plan": _plan()}
    with pytest.raises(ValueError, match=r"stopping.*Restart"):
        action(request)
    assert application.jobs == {}


@pytest.mark.parametrize("provider", ["openai", "gemini", "compatible"])
def test_connection_test_lists_models_without_generating_a_plan(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    _configured(application, provider)
    called: list[str] = []

    def models(provider: str) -> list[str]:
        called.append(provider)
        return ["accessible-model"]

    monkeypatch.setattr(application.planner, "models", models)
    monkeypatch.setattr(
        application.planner,
        "generate",
        lambda *args: pytest.fail("A connection check generated content."),
    )
    result = application.test_provider({"provider": provider})
    assert result["connected"] is True
    assert result["models"] == ["accessible-model"]
    assert called == [provider]
    assert application.jobs == {}
    assert SECRET not in json.dumps(result)


def test_connection_failure_is_reported_without_queuing_work(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def models(provider: str) -> list[str]:
        raise ValueError("API key was rejected. Update Admin settings.")

    monkeypatch.setattr(application.planner, "models", models)
    result = application.test_provider({"provider": "openai"})
    assert result == {
        "connected": False,
        "models": [],
        "message": "API key was rejected. Update Admin settings.",
    }
    assert application.jobs == {}


def test_render_progress_reports_completed_scenes_from_actual_messages() -> None:
    job = server.Job("a" * 32, "render", status="running", total_scenes=3)
    stages = [
        ("Recording local narration 1 of 3", "audio", 0),
        ("Composing original background music", "music", 0),
        ("Rendering scene 1 of 3: Introduction", "render", 0),
        ("Rendering scene 2 of 3: Tangent", "render", 1),
        ("Rendering scene 3 of 3: Slope", "render", 2),
        ("Encoding video and mixing audio", "export", 3),
        ("Video ready", "export", 3),
    ]
    for message, stage, completed in stages:
        server.Application._render_progress(job, message)
        snapshot = job.snapshot()
        assert snapshot["stage"] == stage
        assert snapshot["completed_scenes"] == completed
        assert snapshot["total_scenes"] == 3
        assert snapshot["message"] == message


def test_local_render_publishes_completion_after_real_scene_progress(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def render(
        plan: dict[str, object],
        directory: Path,
        options: dict[str, object],
        progress: Callable[[str], None],
    ) -> None:
        for message in (
            "Rendering scene 1 of 2: A tangent",
            "Rendering scene 2 of 2: A slope",
        ):
            progress(message)
            observed.append(next(iter(application.jobs.values())).snapshot())
        (directory / "project.mp4").write_bytes(b"locally rendered film")
        progress("Video ready")

    monkeypatch.setattr(renderer, "render_project", render)
    job = application.submit_render(
        {"plan": _plan(), "voice_enabled": False, "music_enabled": False}
    )
    application.executor.submit(lambda: None).result(timeout=5)
    assert [snapshot["completed_scenes"] for snapshot in observed] == [0, 1]
    final = job.snapshot()
    assert final["stage"] == "complete"
    assert final["completed_scenes"] == final["total_scenes"] == 2
    assert final["video_url"] == f"/media/{job.id}/project.mp4"


@dataclass
class LocalHTTP:
    """Small real loopback client for provider route boundaries."""

    server: server.StudioServer
    application: server.Application

    def request(
        self,
        method: str,
        path: str,
        data: object = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, object]]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        try:
            connection.request(
                method,
                path,
                body=None if data is None else json.dumps(data).encode(),
                headers=request_headers,
            )
            response = connection.getresponse()
            return (
                response.status,
                dict(response.getheaders()),
                cast(dict[str, object], json.loads(response.read())),
            )
        finally:
            connection.close()


@pytest.fixture
def http(
    application: server.Application, monkeypatch: pytest.MonkeyPatch
) -> Iterator[LocalHTTP]:
    monkeypatch.setattr(server.Handler, "log_message", lambda *args: None)
    monkeypatch.setattr(application.ollama, "models", lambda: ["local:3b"])
    monkeypatch.setattr(renderer, "engine_status", lambda: {"available": True})
    monkeypatch.setattr(renderer, "get_voices", lambda: [])
    try:
        http_server = server.StudioServer(("127.0.0.1", 0), application)
    except PermissionError as error:
        pytest.skip(f"The sandbox blocks loopback sockets: {error}")
    thread = threading.Thread(
        target=http_server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        probe = HTTPConnection("127.0.0.1", http_server.server_port, timeout=5)
        try:
            probe.connect()
        except PermissionError as error:
            pytest.skip(f"The sandbox blocks loopback connections: {error}")
        finally:
            probe.close()
        yield LocalHTTP(http_server, application)
    finally:
        http_server.shutdown()
        thread.join(timeout=2)
        http_server.server_close()


def test_settings_route_returns_only_public_configuration_and_hides_key_files(
    http: LocalHTTP,
) -> None:
    status, headers, snapshot = http.request(
        "POST",
        "/api/settings",
        {
            "provider": "openai",
            "api_key": SECRET,
            "model": "route-test-model",
            "active_provider": "openai",
        },
    )
    assert status == HTTPStatus.OK
    assert headers["Cache-Control"] == "no-store"
    assert snapshot["active_provider"] == "openai"
    assert SECRET not in json.dumps(snapshot)
    for path in ("/api/settings", "/api/status"):
        status, _, snapshot = http.request("GET", path)
        assert status == HTTPStatus.OK
        assert SECRET not in json.dumps(snapshot)
    status, _, _ = http.request("GET", "/media/provider-settings.json")
    assert status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("path", ["/api/settings", "/api/providers/test"])
@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Host": "attacker.example"}, HTTPStatus.FORBIDDEN),
        ({"Origin": "https://attacker.example"}, HTTPStatus.FORBIDDEN),
        ({"Content-Type": "text/plain"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE),
    ],
)
def test_settings_and_connection_routes_retain_same_origin_and_json_protection(
    http: LocalHTTP,
    path: str,
    headers: dict[str, str],
    status: HTTPStatus,
) -> None:
    original = http.application.settings.snapshot()
    response_status, _, response = http.request(
        "POST", path, {"provider": "openai", "api_key": SECRET}, headers
    )
    assert response_status == status
    assert SECRET not in json.dumps(response)
    assert http.application.settings.snapshot() == original


def test_connection_route_uses_saved_server_key_without_echoing_it(
    http: LocalHTTP,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured(http.application)
    monkeypatch.setattr(
        http.application.planner, "models", lambda provider: ["verified-model"]
    )
    status, _, response = http.request(
        "POST", "/api/providers/test", {"provider": "openai"}
    )
    assert status == HTTPStatus.OK
    assert response["connected"] is True
    assert response["models"] == ["verified-model"]
    assert SECRET not in json.dumps(response)


def test_cloud_plan_route_queues_then_polls_validated_math(
    http: LocalHTTP,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured(http.application)
    monkeypatch.setattr(
        http.application.planner, "generate", lambda *args: json.dumps(_plan())
    )
    status, _, response = http.request("POST", "/api/plan", _brief())
    assert status == HTTPStatus.ACCEPTED
    http.application.executor.submit(lambda: None).result(timeout=5)
    status, _, snapshot = http.request("GET", f"/api/jobs/{response['id']}")
    assert status == HTTPStatus.OK
    assert snapshot["stage"] == "review"
    assert cast(dict[str, object], snapshot["plan"])["mode"] == "math"
    assert SECRET not in json.dumps(snapshot)


def test_admin_settings_show_actual_cli_ollama_port_and_reject_endpoint_override(
    http: LocalHTTP,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_url = "http://127.0.0.1:12345"
    monkeypatch.setattr(http.application.ollama, "base", actual_url)
    status, _, snapshot = http.request("GET", "/api/settings")
    assert status == HTTPStatus.OK
    records = cast(list[dict[str, object]], snapshot["providers"])
    local = next(record for record in records if record["id"] == "ollama")
    assert local["base_url"] == actual_url
    status, _, response = http.request(
        "POST",
        "/api/settings",
        {
            "provider": "ollama",
            "base_url": "http://127.0.0.1:9999",
        },
    )
    assert status == HTTPStatus.BAD_REQUEST
    assert "ollama-port" in str(response["error"])
    assert http.application.ollama.base == actual_url
    status, _, snapshot = http.request("GET", "/api/settings")
    records = cast(list[dict[str, object]], snapshot["providers"])
    assert (
        next(record for record in records if record["id"] == "ollama")["base_url"]
        == actual_url
    )


def test_local_compatible_planning_requires_no_key_but_still_validates_math(
    application: server.Application,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application.update_settings(
        {
            "provider": "compatible",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "test-model",
        }
    )
    monkeypatch.setattr(
        application.planner, "generate", lambda *args: json.dumps(_plan())
    )
    job = application.submit_plan(_brief("compatible"))
    application.executor.submit(lambda: None).result(timeout=5)
    assert job.snapshot()["stage"] == "review"
    assert job.snapshot()["status"] == "complete"
    assert application.provider_record("compatible")["scope"] == "local"


@pytest.mark.parametrize(
    "disconnect", [BrokenPipeError, ConnectionResetError, ConnectionAbortedError]
)
def test_media_seek_client_disconnect_finishes_without_worker_error(
    tmp_path: Path,
    disconnect: type[ConnectionError],
) -> None:
    """A seek can close the previous MP4 connection after headers were sent."""
    video = tmp_path / "project.mp4"
    video.write_bytes(bytes(range(100)))
    handler = Mock(spec=server.Handler)
    handler.headers = {"Range": "bytes=4-11"}
    handler.wfile = Mock()
    handler.wfile.write.side_effect = disconnect(
        "The media client closed its connection."
    )

    server.Handler._file(cast(server.Handler, handler), video)

    handler._headers.assert_called_once_with(HTTPStatus.PARTIAL_CONTENT, "video/mp4", 8)
    handler.send_header.assert_any_call("Content-Range", "bytes 4-11/100")
    handler.wfile.write.assert_called_once_with(bytes(range(4, 12)))


@pytest.mark.parametrize(
    "byte_range",
    ["bytes=" + "9" * 5000 + "-", "bytes=-" + "9" * 5000],
    ids=["oversized-start", "oversized-suffix"],
)
def test_oversized_media_offsets_return_a_range_error(
    tmp_path: Path, byte_range: str
) -> None:
    video = tmp_path / "project.mp4"
    video.write_bytes(b"video")
    handler = Mock(spec=server.Handler)
    handler.headers = {"Range": byte_range}
    handler.wfile = Mock()

    server.Handler._file(cast(server.Handler, handler), video)

    handler.send_response.assert_called_once_with(
        HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE
    )
    handler.send_header.assert_any_call("Content-Range", "bytes */5")
    handler.wfile.write.assert_not_called()
