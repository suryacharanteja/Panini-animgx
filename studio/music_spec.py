# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
"""Validate editable music scores and derive scores for older storyboards."""

from __future__ import annotations

import hashlib
import json
import math

MUSIC_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["tempo", "chords"],
    "properties": {
        "tempo": {
            "type": "number",
            "minimum": 40,
            "maximum": 180,
            "description": "Original instrumental tempo in beats per minute.",
        },
        "chords": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {"type": "integer", "minimum": 36, "maximum": 84},
            },
            "description": "Ordered chords using MIDI note numbers; four beats each.",
        },
    },
    "additionalProperties": False,
}


def validate_music(value: object) -> dict[str, object]:
    """Read a bounded score without substituting musical content.

    Args:
        value: Score object with a tempo and one to sixteen MIDI-note chords.

    Returns:
        An independent copy of the validated score.

    Raises:
        ValueError: If the score contains invalid or unsupported values.
    """
    if not isinstance(value, dict) or set(value) != {"tempo", "chords"}:
        raise ValueError("Music needs only tempo and chords.")
    tempo = value["tempo"]
    if (
        isinstance(tempo, bool)
        or not isinstance(tempo, (int, float))
        or not 40 <= tempo <= 180
        or not math.isfinite(tempo)
    ):
        raise ValueError("Music tempo must be between 40 and 180 beats per minute.")
    raw_chords = value["chords"]
    if not isinstance(raw_chords, list) or not 1 <= len(raw_chords) <= 16:
        raise ValueError("Music needs 1 to 16 chords.")
    chords: list[list[int]] = []
    for raw_chord in raw_chords:
        if not isinstance(raw_chord, list) or not 1 <= len(raw_chord) <= 8:
            raise ValueError("Each music chord needs 1 to 8 MIDI notes.")
        notes: list[int] = []
        for note in raw_chord:
            if (
                isinstance(note, bool)
                or not isinstance(note, int)
                or not 36 <= note <= 84
            ):
                raise ValueError("Music MIDI notes must be integers between 36 and 84.")
            notes.append(note)
        chords.append(notes)
    return {"tempo": float(tempo), "chords": chords}


def soundtrack_for_plan(plan: dict[str, object]) -> dict[str, object]:
    """Use a supplied score, or derive repeatable music from a legacy storyboard.

    The content determines tempo, tonal center, chord order, and chord density.
    This preserves old drafts while avoiding a shared canned progression.

    Args:
        plan: Reviewed storyboard, optionally including an editable music score.

    Returns:
        A validated score ready for the local synthesizer.
    """
    if "music" in plan:
        return validate_music(plan["music"])
    storyboard = {
        "title": plan.get("title", ""),
        "mode": plan.get("mode", ""),
        "scenes": plan.get("scenes", []),
    }
    content = json.dumps(
        storyboard, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    seed = hashlib.sha256(content).digest()
    scenes = storyboard["scenes"]
    scene_count = len(scenes) if isinstance(scenes, list) else 1
    chord_count = min(16, max(1, scene_count))
    root = 42 + seed[0] % 15
    chords: list[list[int]] = []
    for index in range(chord_count):
        degree = seed[(index * 2 + 1) % len(seed)] % 7
        density = 2 + seed[(index * 2 + 2) % len(seed)] % 3
        # Evenly spaced scale degrees form a tonal palette without fixed note content.
        chords.append(
            [root + round((degree + step * 2) * 12 / 7) for step in range(density)]
        )
    result: dict[str, object] = {"tempo": 48 + seed[-1] % 65, "chords": chords}
    return validate_music(result)
