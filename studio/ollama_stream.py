# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
"""Read bounded Ollama generation events without waiting on trailing model output."""

from __future__ import annotations

import json
from typing import BinaryIO, cast

MAX_STREAM_BYTES = 2 * 1024 * 1024


def _invalid_constant(value: str) -> object:
    raise ValueError(f"Non-JSON numeric constant: {value}.")


def _object(text: str, name: str) -> dict[str, object]:
    try:
        value: object = json.loads(text, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"Ollama {name} is not valid JSON.") from error
    if not isinstance(value, dict):
        raise ValueError(f"Ollama {name} must be a JSON object.")
    return cast(dict[str, object], value)


class _Storyboard:
    """Track an object's boundary while leaving syntax validation to JSON."""

    def __init__(self) -> None:
        self.fragments: list[str] = []
        self.started = False
        self.complete = False
        self.depth = 0
        self.in_string = False
        self.escaped = False

    def append(self, fragment: str) -> bool:
        self.fragments.append(fragment)
        for character in fragment:
            if self.complete:
                if not character.isspace():
                    raise ValueError(
                        "Ollama storyboard has content after its JSON object."
                    )
            elif not self.started:
                if character.isspace():
                    continue
                if character != "{":
                    raise ValueError("Ollama storyboard must be a JSON object.")
                self.started = True
                self.depth = 1
            elif self.in_string:
                if self.escaped:
                    self.escaped = False
                elif character == "\\":
                    self.escaped = True
                elif character == '"':
                    self.in_string = False
            elif character == '"':
                self.in_string = True
            elif character == "{":
                self.depth += 1
            elif character == "}":
                self.depth -= 1
                self.complete = self.depth == 0
        return self.complete

    def result(self) -> dict[str, object]:
        joined = "".join(self.fragments)
        _object(joined, "storyboard")
        return {"response": joined}


def read_generation(response: BinaryIO) -> dict[str, object]:
    """Accumulate response fragments until an exact, complete JSON object is ready.

    Args:
        response: Binary NDJSON stream returned by Ollama's generation endpoint.

    Returns:
        The original joined model response, without edits or repairs.

    Raises:
        ValueError: If an event or storyboard is invalid, generation fails, the
            stream exceeds two MiB, or it ends before a complete storyboard.
    """
    storyboard = _Storyboard()
    line = bytearray()
    total = 0
    while True:
        chunk = response.readline(MAX_STREAM_BYTES + 1)
        if chunk:
            total += len(chunk)
            if total > MAX_STREAM_BYTES:
                raise ValueError("Ollama generation stream exceeded the size limit.")
            line.extend(chunk)
            if len(line) > MAX_STREAM_BYTES:
                raise ValueError("Ollama generation event exceeded the size limit.")
            if not line.endswith(b"\n"):
                continue
        elif not line:
            raise ValueError(
                "Ollama generation stream ended before a complete storyboard."
            )

        try:
            event_text = line.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Ollama generation event is not UTF-8 text.") from error
        event = _object(event_text, "generation event")
        line.clear()
        if "error" in event:
            raise ValueError("Ollama reported a generation error.")
        fragment = event.get("response", "")
        if not isinstance(fragment, str):
            raise ValueError("Ollama generation response fragment must be text.")
        done = event.get("done", False)
        if not isinstance(done, bool):
            raise ValueError("Ollama generation done flag must be boolean.")
        if storyboard.append(fragment):
            return storyboard.result()
        if done:
            try:
                return storyboard.result()
            except ValueError as error:
                raise ValueError(
                    "Ollama generation ended with an incomplete or invalid storyboard."
                ) from error
        if not chunk:
            raise ValueError(
                "Ollama generation stream ended before a complete storyboard."
            )
