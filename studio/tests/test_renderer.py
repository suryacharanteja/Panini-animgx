# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT

"""Offline audio, narration timing and authored-content renderer boundaries."""

import json
import wave
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from studio import renderer


def _plan(duration: float = 3) -> dict[str, object]:
    return {
        "title": "Test",
        "mode": "explainer",
        "scenes": [
            {
                "title": "A short scene",
                "narration": "Hello from Panini Studio.",
                "visual": "composition",
                "composition": {
                    "elements": [
                        {
                            "kind": "text",
                            "text": "Authored content",
                            "start": 0,
                            "end": 0.2,
                        }
                    ]
                },
                "duration": duration,
                "background": "#142033",
                "accent": "#8DABFF",
            }
        ],
    }


def test_music_is_original_pcm_with_bounded_volume_and_fades(tmp_path: Path) -> None:
    path = tmp_path / "music.wav"
    renderer._make_music(path, 2, 0.12)
    with wave.open(str(path), "rb") as recording:
        assert recording.getnchannels() == 1
        assert recording.getsampwidth() == 2
        assert recording.getframerate() == 48_000
        assert recording.getnframes() == 96_000
        samples = np.frombuffer(recording.readframes(96_000), dtype="<i2") / 32767
    assert samples[0] == 0
    assert np.max(np.abs(samples)) < 0.12
    assert np.max(np.abs(samples[40_000:50_000])) > 0.015
    assert np.max(np.abs(samples[-100:])) < 0.001
    duplicate = tmp_path / "duplicate.wav"
    renderer._make_music(duplicate, 2, 0.12)
    assert duplicate.read_bytes() == path.read_bytes()


@pytest.mark.parametrize(
    ("duration", "volume"),
    [(0, 0.1), (float("inf"), 0.1), (2, -0.1), (2, 0.4), (2, float("nan"))],
)
def test_music_rejects_invalid_duration_and_volume(
    tmp_path: Path, duration: float, volume: float
) -> None:
    with pytest.raises(ValueError, match="Music"):
        renderer._make_music(tmp_path / "invalid.wav", duration, volume)


def test_narration_extends_shot_and_keeps_captions_within_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, Path]] = []

    def speech(text: str, voice: str, path: Path) -> float:
        calls.append((text, voice, path))
        return 7.0

    monkeypatch.setattr(renderer, "_synthesize_narration", speech)
    progress: list[str] = []
    shots = renderer._prepare_shots(
        _plan(), tmp_path, {"voice_enabled": True, "voice": "Local"}, progress.append
    )
    assert shots[0].duration == pytest.approx(7.75)
    assert shots[0].audio == tmp_path / "voice-01.wav"
    assert calls == [("Hello from Panini Studio.", "Local", tmp_path / "voice-01.wav")]
    (caption,) = renderer._captions(shots)
    assert caption.start == pytest.approx(0.35)
    assert caption.end == pytest.approx(7.35)


def test_disabled_voice_does_not_call_speech(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(text: str, voice: str, path: Path) -> float:
        raise AssertionError("Speech should not run")

    monkeypatch.setattr(renderer, "_synthesize_narration", forbidden)
    shots = renderer._prepare_shots(
        _plan(), tmp_path, {"voice_enabled": False}, lambda _message: None
    )
    assert shots[0].audio is None
    assert shots[0].duration == 3


def test_captions_end_with_speech_when_scene_is_longer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        renderer, "_synthesize_narration", lambda _text, _voice, _path: 2.0
    )
    shots = renderer._prepare_shots(
        _plan(12), tmp_path, {"voice_enabled": True}, lambda _message: None
    )
    (caption,) = renderer._captions(shots)
    assert shots[0].duration == 12
    assert caption.end == pytest.approx(2.35)


def test_engine_configuration_restored_after_failed_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import manimgx as m

    original = (m.config.pixel_width, m.config.pixel_height, m.config.frame_rate)

    def fail(self: object, video: Path, *, preset: str, crf: float) -> None:
        assert (m.config.pixel_width, m.config.pixel_height, m.config.frame_rate) == (
            960,
            540,
            24,
        )
        raise RuntimeError("GPU unavailable")

    monkeypatch.setattr(m.Scene, "render", fail)
    with pytest.raises(RuntimeError, match="GPU unavailable"):
        renderer.render_project(_plan(), tmp_path, {}, lambda _message: None)
    assert (
        m.config.pixel_width,
        m.config.pixel_height,
        m.config.frame_rate,
    ) == original


def test_caption_files_have_contiguous_numbering_and_correct_timestamps(
    tmp_path: Path,
) -> None:
    shots = renderer._prepare_shots(_plan(), tmp_path, {}, lambda _message: None)
    renderer._write_captions(tmp_path, shots * 2)
    srt = (tmp_path / "project.srt").read_text(encoding="utf-8")
    assert "1\n00:00:00,350 --> 00:00:02,600" in srt
    assert "2\n00:00:03,350 --> 00:00:05,600" in srt
    vtt = (tmp_path / "project.vtt").read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT\n")
    assert "00:00:03.350 --> 00:00:05.600" in vtt


def test_speech_passes_untrusted_text_as_json_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    def powershell(script: str, payload: dict[str, str] | None = None) -> str:
        assert script == renderer._SPEECH_SCRIPT
        assert payload is not None
        captured.update(payload)
        with wave.open(payload["path"], "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(16_000)
            recording.writeframes(b"\0\0" * 16_000)
        return ""

    monkeypatch.setattr(renderer, "_powershell", powershell)
    text = "Hello; $(Remove-Item data) `example` 'quotes' हिन्दी"
    assert renderer._synthesize_narration(text, "Voice", tmp_path / "voice.wav") == 1
    assert json.loads(json.dumps(captured))["text"] == text


@pytest.mark.parametrize(
    ("response", "expected"),
    [("[]", []), ('["One", "Two"]', ["One", "Two"]), ('"One"', ["One"]), ("null", [])],
)
def test_installed_voice_listing(
    response: str, expected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(renderer, "_powershell", lambda _script: response)
    assert renderer.get_voices() == expected


def test_long_captions_cover_narration_without_overlapping(tmp_path: Path) -> None:
    plan = _plan(15)
    scenes = plan["scenes"]
    assert isinstance(scenes, list)
    scenes[0]["narration"] = " ".join(f"word{index}" for index in range(75))
    shots = renderer._prepare_shots(plan, tmp_path, {}, lambda _message: None)
    captions = renderer._captions(shots)
    assert len(captions) > 1
    assert " ".join(caption.text for caption in captions) == scenes[0]["narration"]
    assert captions[0].start == pytest.approx(0.35)
    assert captions[-1].end == pytest.approx(14.6)
    for previous, current in pairwise(captions):
        assert previous.end == pytest.approx(current.start)


@pytest.mark.parametrize(
    "visual", ["orbit", "process", "bars", "character", "landscape", "unknown"]
)
def test_preset_visuals_never_generate_canned_content_or_audio(
    visual: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import manimgx as m

    plan = _plan()
    scenes = plan["scenes"]
    assert isinstance(scenes, list)
    scenes.append({**scenes[0], "visual": visual})

    def forbidden_speech(text: str, voice: str, path: Path) -> float:
        raise AssertionError("Unsupported visuals must fail before narration")

    def forbidden_render(self: object, video: Path, *, preset: str, crf: float) -> None:
        raise AssertionError("Unsupported visuals must fail before native rendering")

    monkeypatch.setattr(renderer, "_synthesize_narration", forbidden_speech)
    monkeypatch.setattr(m.Scene, "render", forbidden_render)
    with pytest.raises(ValueError, match=r"Scene 2.*authored composition.*math tool"):
        renderer.render_project(
            plan, tmp_path, {"voice_enabled": True}, lambda _message: None
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "background",
    ["#000000", "#FFFFFF", "#EAF0E8", "#FF0000", "#777777", "#162033", "#00FF00"],
)
def test_text_contrast_meets_wcag_aa_for_scene_background(background: str) -> None:
    foreground = renderer._foreground_color(background)
    levels = [renderer._luminance(color) for color in (background, foreground)]
    assert (max(levels) + 0.05) / (min(levels) + 0.05) >= 4.5


def test_light_background_chooses_dark_text_for_authored_content() -> None:
    foreground = renderer._foreground_color("#EAF0E8")
    assert foreground == "#172033"


def test_webvtt_preserves_literal_markup_and_arrows_in_narration(
    tmp_path: Path,
) -> None:
    plan = _plan()
    scenes = plan["scenes"]
    assert isinstance(scenes, list)
    scenes[0]["narration"] = "Use <b>literal</b> & keep --> visible."
    shots = renderer._prepare_shots(plan, tmp_path, {}, lambda _message: None)
    renderer._write_captions(tmp_path, shots)
    assert "Use &lt;b&gt;literal&lt;/b&gt; &amp; keep --&gt; visible." in (
        tmp_path / "project.vtt"
    ).read_text(encoding="utf-8")


def test_failed_export_preserves_the_previous_complete_artifact_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import manimgx as m

    previous = {
        name: f"Previous {name}".encode()
        for name in (
            "project.mp4",
            "project.srt",
            "project.vtt",
            "timing.json",
            "music.wav",
        )
    }
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)

    def fail(self: m.Scene, path: Path, *, preset: str, crf: float) -> None:
        path.write_bytes(b"incomplete video")
        raise RuntimeError("Encoding failed")

    monkeypatch.setattr(m.Scene, "render", fail)
    with pytest.raises(RuntimeError, match="Encoding failed"):
        renderer.render_project(
            _plan(10), tmp_path, {"music_enabled": True}, lambda _message: None
        )
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == previous


def test_publication_failure_rolls_back_video_captions_and_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import manimgx as m

    previous = {
        name: f"Previous {name}".encode()
        for name in ("project.mp4", "project.srt", "project.vtt", "timing.json")
    }
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)

    def render(self: m.Scene, path: Path, *, preset: str, crf: float) -> None:
        path.write_bytes(b"new video")

    replace = Path.replace

    def unavailable(self: Path, target: Path) -> Path:
        if (
            self.name == "project.mp4"
            and self.parent.name.startswith(".render-")
            and target.parent == tmp_path
        ):
            raise PermissionError("Export destination is unavailable")
        return replace(self, target)

    monkeypatch.setattr(m.Scene, "render", render)
    monkeypatch.setattr(Path, "replace", unavailable)
    progress: list[str] = []
    with pytest.raises(PermissionError, match="destination"):
        renderer.render_project(_plan(10), tmp_path, {}, progress.append)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == previous
    assert "Video ready" not in progress


def test_successful_export_publishes_all_artifacts_after_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import manimgx as m

    (tmp_path / "project.mp4").write_bytes(b"previous video")

    def render(self: m.Scene, path: Path, *, preset: str, crf: float) -> None:
        assert (tmp_path / "project.mp4").read_bytes() == b"previous video"
        assert not (tmp_path / "project.vtt").exists()
        assert path.parent != tmp_path
        path.write_bytes(b"new video")

    monkeypatch.setattr(m.Scene, "render", render)
    progress: list[str] = []
    target = renderer.render_project(
        _plan(), tmp_path, {"music_enabled": True}, progress.append
    )
    assert target == tmp_path / "project.mp4"
    assert target.read_bytes() == b"new video"
    assert {path.name for path in tmp_path.iterdir()} == {
        "project.mp4",
        "project.srt",
        "project.vtt",
        "timing.json",
        "music.wav",
    }
    assert progress[-1] == "Video ready"


@pytest.mark.parametrize("block_all_restores", [False, True])
def test_failed_rollback_retains_originals_and_reports_the_recovery_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, block_all_restores: bool
) -> None:
    import manimgx as m

    previous = {
        name: f"Previous {name}".encode()
        for name in ("project.mp4", "project.srt", "project.vtt", "timing.json")
    }
    for name, content in previous.items():
        (tmp_path / name).write_bytes(content)

    def render(self: m.Scene, path: Path, *, preset: str, crf: float) -> None:
        path.write_bytes(b"new video")

    replace = Path.replace
    attempted_restores: list[str] = []

    def unavailable(self: Path, target: Path) -> Path:
        if self.parent.name == "previous":
            attempted_restores.append(self.name)
            if block_all_restores or self.name == "project.mp4":
                raise PermissionError("The previous export is still locked")
        elif self.name == "project.mp4" and target.parent == tmp_path:
            raise PermissionError("The export destination is locked")
        return replace(self, target)

    monkeypatch.setattr(m.Scene, "render", render)
    monkeypatch.setattr(Path, "replace", unavailable)
    progress: list[str] = []
    with pytest.raises(renderer._RenderRecoveryError, match="Recovery files") as failed:
        renderer.render_project(_plan(10), tmp_path, {}, progress.append)
    recovery = failed.value.recovery_directory
    assert recovery.is_dir()
    assert recovery.parent.parent == tmp_path
    assert str(recovery) in str(failed.value)
    assert str(tmp_path) in str(failed.value)
    assert set(attempted_restores) == set(previous)
    retained = {path.name: path.read_bytes() for path in recovery.iterdir()}
    assert retained == (
        previous if block_all_restores else {"project.mp4": previous["project.mp4"]}
    )
    if not block_all_restores:
        assert {
            path.name: path.read_bytes()
            for path in tmp_path.iterdir()
            if path.is_file()
        } == {
            name: content for name, content in previous.items() if name != "project.mp4"
        }
    assert "Video ready" not in progress
