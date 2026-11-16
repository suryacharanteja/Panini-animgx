# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
"""Validate draft-specific soundtrack content and MIDI synthesis behavior."""

import wave
from pathlib import Path

import numpy as np
import pytest
from studio import renderer
from studio.music_spec import soundtrack_for_plan, validate_music


def _draft(title: str) -> dict[str, object]:
    return {
        "title": title,
        "mode": "explainer",
        "scenes": [{"title": title, "narration": f"Explain {title}.", "duration": 6}],
    }


def _samples(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as recording:
        return np.frombuffer(recording.readframes(recording.getnframes()), dtype="<i2")


def _dominant_frequency(samples: np.ndarray) -> float:
    spectrum = np.abs(np.fft.rfft(samples.astype(float)))
    frequencies = np.fft.rfftfreq(len(samples), 1 / 48_000)
    return float(frequencies[np.argmax(spectrum)])


def test_legacy_scores_depend_on_storyboard_content_and_ignore_key_order() -> None:
    first = _draft("Ocean currents")
    second = _draft("Forest ecosystems")
    score = soundtrack_for_plan(first)
    assert score != soundtrack_for_plan(second)
    assert score == soundtrack_for_plan(dict(reversed(list(first.items()))))
    assert score == validate_music(score)


def test_supplied_score_is_preserved_as_an_independent_copy() -> None:
    chords = [[44, 51, 56], [47, 54]]
    supplied: dict[str, object] = {"tempo": 81.5, "chords": chords}
    plan = _draft("Custom score")
    plan["music"] = supplied
    score = soundtrack_for_plan(plan)
    assert score == supplied
    assert score is not supplied
    chords[0][0] = 60
    assert score["chords"] == [[44, 51, 56], [47, 54]]


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"tempo": 72},
        {"tempo": 72, "chords": [[48]], "file": "external.wav"},
        {"tempo": True, "chords": [[48]]},
        {"tempo": "72", "chords": [[48]]},
        {"tempo": float("inf"), "chords": [[48]]},
        {"tempo": float("nan"), "chords": [[48]]},
        {"tempo": 39, "chords": [[48]]},
        {"tempo": 181, "chords": [[48]]},
        {"tempo": 72, "chords": []},
        {"tempo": 72, "chords": [[48]] * 17},
        {"tempo": 72, "chords": [[]]},
        {"tempo": 72, "chords": [[48] * 9]},
        {"tempo": 72, "chords": [[35]]},
        {"tempo": 72, "chords": [[85]]},
        {"tempo": 72, "chords": [[48.0]]},
        {"tempo": 72, "chords": [[True]]},
    ],
)
def test_invalid_music_does_not_substitute_a_canned_score(value: object) -> None:
    with pytest.raises(ValueError, match=r"Music|music"):
        validate_music(value)
    with pytest.raises(ValueError, match=r"Music|music"):
        soundtrack_for_plan({"music": value})


def test_different_storyboards_produce_different_pcm_soundtracks(
    tmp_path: Path,
) -> None:
    paths = [tmp_path / f"music-{index}.wav" for index in range(2)]
    for path, title in zip(paths, ("Ocean currents", "Forest ecosystems"), strict=True):
        renderer._make_music(path, 2, 0.12, soundtrack_for_plan(_draft(title)))
    assert paths[0].read_bytes() != paths[1].read_bytes()


@pytest.mark.parametrize("note", [48, 69, 84])
def test_supplied_midi_note_sets_the_audible_pitch(tmp_path: Path, note: int) -> None:
    path = tmp_path / "score.wav"
    renderer._make_music(path, 2, 0.12, {"tempo": 60, "chords": [[note]]})
    expected_frequency = 440 * 2 ** ((note - 69) / 12)
    assert _dominant_frequency(_samples(path)[48_000:72_000]) == pytest.approx(
        expected_frequency, abs=2
    )


def test_tempo_changes_when_the_next_supplied_chord_is_heard(tmp_path: Path) -> None:
    paths = [tmp_path / f"tempo-{tempo}.wav" for tempo in (60, 120)]
    for path, tempo in zip(paths, (60, 120), strict=True):
        renderer._make_music(path, 7, 0.12, {"tempo": tempo, "chords": [[69], [76]]})
    slow = _dominant_frequency(_samples(paths[0])[124_800:163_200])
    fast = _dominant_frequency(_samples(paths[1])[124_800:163_200])
    assert slow == pytest.approx(440, abs=2)
    assert fast == pytest.approx(440 * 2 ** (7 / 12), abs=2)


def test_supplied_chords_support_different_note_counts(tmp_path: Path) -> None:
    path = tmp_path / "variable-chords.wav"
    renderer._make_music(
        path, 4, 0.12, {"tempo": 120, "chords": [[69], [60, 64, 67, 72]]}
    )
    samples = _samples(path)
    assert len(samples) == 4 * 48_000
    assert np.max(np.abs(samples)) > 0
    assert samples[0] == 0
    assert np.max(np.abs(samples[-100:])) < 33
