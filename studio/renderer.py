# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT

"""Render reviewed scene compositions, mathematical tools and offline audio."""

from __future__ import annotations

import html
import importlib
import json
import math
import os
import shutil
import subprocess
import textwrap
import threading
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import mkdtemp
from typing import cast

import numpy as np

from studio.math_spec import MATH_VISUALS
from studio.music_spec import soundtrack_for_plan

_RATE = 48_000
_RENDER_LOCK = threading.Lock()
_POWERSHELL_HEADER = """
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
"""
_VOICES_SCRIPT = (
    _POWERSHELL_HEADER
    + """
try {
    $names = @($speaker.GetInstalledVoices() |
        Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
    ConvertTo-Json -InputObject $names -Compress
} finally { $speaker.Dispose() }
"""
)
_SPEECH_SCRIPT = (
    _POWERSHELL_HEADER
    + """
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($request.voice) { $speaker.SelectVoice([string]$request.voice) }
    $speaker.Rate = 0
    $speaker.SetOutputToWaveFile([string]$request.path)
    $speaker.Speak([string]$request.text)
    $speaker.SetOutputToNull()
} finally { $speaker.Dispose() }
"""
)


@dataclass(frozen=True)
class _Shot:
    title: str
    narration: str
    visual: str
    background: str
    accent: str
    duration: float
    audio: Path | None
    spoken_duration: float | None
    math: dict[str, object] = field(default_factory=dict)
    composition: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _Caption:
    start: float
    end: float
    text: str


def engine_status() -> dict[str, object]:
    """Return whether the installed native engine can be imported.

    A successful import does not probe GPU rendering; export exercises the GPU.
    """
    try:
        importlib.import_module("manimgx._engine")
    except (ImportError, OSError, RuntimeError) as error:
        return {"available": False, "error": str(error)}
    return {"available": True, "error": ""}


def _powershell(script: str, payload: dict[str, str] | None = None) -> str:
    executable = shutil.which("powershell.exe")
    if os.name != "nt" or executable is None:
        raise RuntimeError(
            "Offline narration requires Windows PowerShell and System.Speech."
        )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", script],
        input=json.dumps(payload or {}, ensure_ascii=False),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=0x08000000,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or "Windows speech synthesis failed."
        raise RuntimeError(detail[-800:])
    return result.stdout.strip().lstrip("\ufeff")


def get_voices() -> list[str]:
    """List enabled, installed Windows speech voices without network access."""
    try:
        parsed: object = json.loads(_powershell(_VOICES_SCRIPT))
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
        return []
    if isinstance(parsed, str):
        return [parsed]
    if isinstance(parsed, list):
        return [name for name in parsed if isinstance(name, str)]
    return []


def _synthesize_narration(text: str, voice: str, path: Path) -> float:
    _powershell(
        _SPEECH_SCRIPT, {"text": text, "voice": voice, "path": str(path.resolve())}
    )
    with wave.open(str(path), "rb") as recording:
        duration = recording.getnframes() / recording.getframerate()
    if duration <= 0:
        raise RuntimeError("The selected Windows voice produced an empty recording.")
    return duration


def _prepare_shots(
    plan: dict[str, object],
    directory: Path,
    options: dict[str, object],
    progress: Callable[[str], None],
) -> list[_Shot]:
    shots: list[_Shot] = []
    scenes = cast(list[dict[str, object]], plan["scenes"])
    for index, scene in enumerate(scenes):
        visual = scene.get("visual")
        if not isinstance(visual, str) or visual not in {"composition", *MATH_VISUALS}:
            raise ValueError(
                f"Scene {index + 1} uses an unsupported visual. "
                "Replace old visual presets with an authored composition or an "
                "explicit math tool, then plan again."
            )
    voice = str(options.get("voice", ""))
    for index, scene in enumerate(scenes):
        narration = str(scene["narration"]).strip()
        duration = float(cast(float, scene["duration"]))
        audio = None
        spoken_duration = None
        if options.get("voice_enabled") and narration:
            progress(f"Recording local narration {index + 1} of {len(scenes)}")
            audio = directory / f"voice-{index + 1:02}.wav"
            spoken_duration = _synthesize_narration(narration, voice, audio)
            duration = max(duration, 0.35 + spoken_duration + 0.4)
        shots.append(
            _Shot(
                str(scene["title"]),
                narration,
                str(scene["visual"]),
                str(scene["background"]),
                str(scene["accent"]),
                duration,
                audio,
                spoken_duration,
                cast(dict[str, object], scene.get("math", {})),
                cast(dict[str, object], scene.get("composition", {})),
            )
        )
    return shots


def _make_music(
    path: Path,
    duration: float,
    volume: float,
    score: dict[str, object] | None = None,
) -> None:
    """Synthesize the reviewed MIDI score as a bounded, faded mono PCM WAV."""
    from studio.music_spec import soundtrack_for_plan, validate_music

    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Music duration must be positive and finite.")
    if not math.isfinite(volume) or not 0 <= volume <= 0.3:
        raise ValueError("Music volume must be between 0 and 0.3.")
    reviewed = (
        validate_music(score)
        if score is not None
        else soundtrack_for_plan({"scenes": [{"duration": duration}]})
    )
    tempo = float(cast(float, reviewed["tempo"]))
    midi_chords = cast(list[list[int]], reviewed["chords"])
    chords = [
        440 * 2 ** ((np.array(notes, dtype=np.float64) - 69) / 12)
        for notes in midi_chords
    ]
    chord_duration = 4 * 60 / tempo
    samples = round(duration * _RATE)
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(_RATE)
        for offset in range(0, samples, _RATE):
            times = (
                np.arange(offset, min(offset + _RATE, samples), dtype=np.float64)
                / _RATE
            )
            chord_indices = (times // chord_duration).astype(int) % len(chords)
            pad = np.zeros(times.shape)
            bass = np.zeros(times.shape)
            for index in np.unique(chord_indices):
                selected = chord_indices == index
                note_times = times[selected]
                notes = chords[index]
                phases = 2 * np.pi * note_times[:, None] * notes
                pad[selected] = (np.sin(phases) + 0.2 * np.sin(phases * 2)).mean(axis=1)
                bass[selected] = 0.3 * np.sin(2 * np.pi * min(notes) * 0.5 * note_times)
            pulse = 0.85 + 0.15 * np.sin(2 * np.pi * (tempo / 60) * times / 4)
            chord_time = times % chord_duration
            chord_fade = np.minimum(
                np.clip(chord_time / 0.12, 0, 1),
                np.clip((chord_duration - chord_time) / 0.15, 0, 1),
            )
            fade = np.minimum(
                np.clip(times / 0.8, 0, 1), np.clip((duration - times) / 1.2, 0, 1)
            )
            sound = (pad + bass) * pulse * fade * chord_fade * volume * 0.65
            recording.writeframesraw(
                (np.clip(sound, -1, 1) * 32767).astype("<i2").tobytes()
            )


def _captions(shots: list[_Shot]) -> list[_Caption]:
    captions: list[_Caption] = []
    start = 0.0
    for shot in shots:
        lines = textwrap.wrap(" ".join(shot.narration.split()), width=86)
        if lines:
            begin = start + 0.35
            end = (
                begin + shot.spoken_duration
                if shot.spoken_duration is not None
                else start + shot.duration - 0.4
            )
            weights = [len(line.split()) for line in lines]
            span = (end - begin) / sum(weights)
            for line, weight in zip(lines, weights, strict=True):
                next_time = begin + weight * span
                captions.append(_Caption(begin, next_time, line))
                begin = next_time
        start += shot.duration
    return captions


def _timestamp(seconds: float, *, vtt: bool = False) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, milliseconds = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02}:{minutes:02}:{seconds_part:02}{separator}{milliseconds:03}"


def _write_captions(directory: Path, shots: list[_Shot]) -> None:
    captions = _captions(shots)
    srt: list[str] = []
    vtt: list[str] = ["WEBVTT\n"]
    for index, caption in enumerate(captions, start=1):
        srt.append(
            f"{index}\n{_timestamp(caption.start)} --> {_timestamp(caption.end)}\n{caption.text}\n"
        )
        vtt.append(
            f"{_timestamp(caption.start, vtt=True)} --> {_timestamp(caption.end, vtt=True)}\n"
            f"{html.escape(caption.text, quote=False)}\n"
        )
    (directory / "project.srt").write_text("\n".join(srt), encoding="utf-8")
    (directory / "project.vtt").write_text("\n".join(vtt), encoding="utf-8")


def _luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return sum(
        channel * weight
        for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True)
    )


def _foreground_color(background: str) -> str:
    """Choose text with at least WCAG AA contrast against the scene background."""
    luminance = _luminance(background)

    def contrast(color: str) -> float:
        other = _luminance(color)
        return (max(luminance, other) + 0.05) / (min(luminance, other) + 0.05)

    color = max(("#172033", "#FFFFFF"), key=contrast)
    return color if contrast(color) >= 4.5 else "#000000"


def _render_staged_project(
    plan: dict[str, object],
    directory: Path,
    options: dict[str, object],
    progress: Callable[[str], None],
) -> Path:
    """Render a validated storyboard to MP4 with captions and optional offline audio.

    Args:
        plan: Reviewed storyboard with authored compositions or mathematical tools.
        directory: Project directory for the video and generated audio.
        options: Voice, music and preview/final quality options validated by the server.
        progress: Receives short progress descriptions for the local interface.

    Returns:
        Path to the completed project.mp4.
    """
    import manimgx as m

    directory.mkdir(parents=True, exist_ok=True)
    shots = _prepare_shots(plan, directory, options, progress)
    if not shots:
        raise ValueError("A storyboard needs at least one scene.")
    total = sum(shot.duration for shot in shots)
    music = None
    if options.get("music_enabled"):
        progress("Composing original background music")
        music = directory / "music.wav"
        _make_music(
            music,
            total,
            float(cast(float, options.get("music_volume", 0.12))),
            soundtrack_for_plan(plan),
        )
    _write_captions(directory, shots)
    (directory / "timing.json").write_text(
        json.dumps(
            {
                "duration": total,
                "scenes": [
                    {"title": shot.title, "duration": shot.duration} for shot in shots
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    preview = options.get("quality", "preview") == "preview"
    target = directory / "project.mp4"
    temporary = directory / "project.partial.mp4"

    class ProjectScene(m.Scene):
        def construct(self) -> None:
            if music is not None:
                self.add_sound(music)
            for index, shot in enumerate(shots):
                progress(f"Rendering scene {index + 1} of {len(shots)}: {shot.title}")
                self.camera.background_color = shot.background
                foreground = _foreground_color(shot.background)
                if shot.audio is not None:
                    self.add_sound(shot.audio, time_offset=0.35)
                if shot.visual == "composition":
                    from studio.composition_scenes import animate_composition

                    visual = animate_composition(
                        self, shot.composition, shot.accent, foreground, shot.duration
                    )
                    self.remove(*visual.get_family())
                    continue
                title = m.Text(
                    shot.title, font="Noto Sans", font_size=46, color=foreground
                )
                if title.width > 11.7:
                    title.scale_to_fit_width(11.7)
                title.move_to([0, 2.9, 0])
                eyebrow = m.Text(
                    f"{str(plan['title'])[:70]}  ·  {index + 1:02} / {len(shots):02}",
                    font="Noto Sans",
                    font_size=18,
                    color=foreground,
                ).move_to([0, 3.52, 0])
                if eyebrow.width > 12:
                    eyebrow.scale_to_fit_width(12)
                self.add(eyebrow)
                from studio.math_scenes import animate_math

                self.play(m.FadeIn(title), run_time=0.55)
                visual = animate_math(
                    self,
                    shot.visual,
                    shot.math,
                    shot.accent,
                    foreground,
                    shot.duration - 0.95,
                )
                self.play(
                    m.FadeOut(visual),
                    m.FadeOut(title),
                    m.FadeOut(eyebrow),
                    run_time=0.4,
                )
            progress("Encoding video and mixing audio")

    with _RENDER_LOCK:
        original = (m.config.pixel_width, m.config.pixel_height, m.config.frame_rate)
        try:
            m.config.pixel_width, m.config.pixel_height = (
                (960, 540) if preview else (1920, 1080)
            )
            m.config.frame_rate = 24 if preview else 30
            ProjectScene().render(
                temporary,
                preset="ultrafast" if preview else "medium",
                crf=23 if preview else 19,
            )
            temporary.replace(target)
        finally:
            m.config.pixel_width, m.config.pixel_height, m.config.frame_rate = original
    return target


class _RenderRecoveryError(RuntimeError):
    """Report an incomplete rollback without deleting the saved originals."""

    def __init__(self, backups: Path, directory: Path) -> None:
        self.recovery_directory = backups.resolve()
        super().__init__(
            "Export publication failed and some previous files could not be restored. "
            f"Recovery files are preserved at {self.recovery_directory}. "
            "Close applications using the export files, then restore any saved originals "
            f"to {directory.resolve()}."
        )


def _publish_render(staging: Path, directory: Path) -> None:
    """Replace the completed export together, restoring the previous files on failure."""
    backups = staging / "previous"
    backups.mkdir()
    artifacts = sorted(
        (path for path in staging.iterdir() if path.is_file()),
        key=lambda path: path.name == "project.mp4",
    )
    replaced: list[Path] = []
    saved: list[Path] = []
    try:
        for artifact in artifacts:
            target = directory / artifact.name
            if target.exists():
                backup = backups / artifact.name
                target.replace(backup)
                saved.append(backup)
            artifact.replace(target)
            replaced.append(target)
    except OSError:
        rollback_errors: list[OSError] = []
        saved_names = {backup.name for backup in saved}
        # Replace a new file directly with its saved original. Remove only exports
        # that had no previous file, and continue recovering after a locked file.
        for target in reversed(replaced):
            if target.name not in saved_names:
                try:
                    target.unlink(missing_ok=True)
                except OSError as error:
                    rollback_errors.append(error)
        for backup in reversed(saved):
            try:
                backup.replace(directory / backup.name)
            except OSError as error:
                rollback_errors.append(error)
        if rollback_errors:
            raise _RenderRecoveryError(backups, directory) from rollback_errors[0]
        raise


def render_project(
    plan: dict[str, object],
    directory: Path,
    options: dict[str, object],
    progress: Callable[[str], None],
) -> Path:
    """Render a reviewed storyboard and publish its video, captions and timing together.

    Args:
        plan: Reviewed storyboard with authored compositions or mathematical tools.
        directory: Project directory for the video and generated audio.
        options: Voice, music and preview/final quality options validated by the server.
        progress: Receives short progress descriptions for the local interface.

    Returns:
        Path to the completed project.mp4. A failed export preserves the previous files
        or, if a file is locked during recovery, reports where its backup is retained.
    """
    directory.mkdir(parents=True, exist_ok=True)
    resolved_directory = directory.resolve()
    staging = Path(mkdtemp(prefix=".render-", dir=resolved_directory))
    preserve_recovery = False
    try:
        _render_staged_project(plan, staging, options, progress)
        _publish_render(staging, directory)
    except _RenderRecoveryError:
        preserve_recovery = True
        raise
    finally:
        if not preserve_recovery:
            if staging.resolve().parent != resolved_directory:
                raise RuntimeError(
                    "The render staging directory moved outside the project."
                )
            shutil.rmtree(staging)
    progress("Video ready")
    return directory / "project.mp4"
