# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
"""Check the actual Studio color roles against normal-text contrast requirements."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

STYLES = Path(__file__).resolve().parents[1] / "web" / "styles.css"


def _declarations(styles: str, selector: str) -> dict[str, str]:
    styles = re.sub(r"/\*.*?\*/", "", styles, flags=re.DOTALL)
    result: dict[str, str] = {}
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", styles):
        if selector not in [item.strip() for item in selectors.split(",")]:
            continue
        for declaration in declarations.split(";"):
            if ":" in declaration:
                name, value = declaration.split(":", 1)
                result[name.strip()] = value.strip()
    return result


def _luminance(color: str) -> float:
    color = color.removeprefix("#")
    if len(color) == 3:
        color = "".join(channel * 2 for channel in color)
    channels = [int(color[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return sum(
        value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722))
    )


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_luminance(foreground), _luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


class FrontendContrastTests(unittest.TestCase):
    """Protect legibility while allowing palette changes that meet the same threshold."""

    def test_secondary_text_and_placeholders_meet_normal_text_contrast(self) -> None:
        styles = STYLES.read_text(encoding="utf-8")
        roles = _declarations(styles, ":root")
        surfaces = [roles["--canvas"], roles["--surface"], "#f8faf8", "#e9f1e9"]
        for selector in (
            ".field-hint",
            ".scene-controls label",
            ".math-field label",
            ".preview-caption small",
            ".workspace-footer",
            "textarea::placeholder",
            "input::placeholder",
        ):
            color = _declarations(styles, selector)["color"]
            if color.startswith("var("):
                color = roles[color[4:-1]]
            for background in surfaces:
                with self.subTest(selector=selector, background=background):
                    assert _contrast(color, background) >= 4.5
        for selector in ("textarea::placeholder", "input::placeholder"):
            assert _declarations(styles, selector)["opacity"] == "1"

    def test_primary_actions_and_validation_feedback_meet_normal_text_contrast(
        self,
    ) -> None:
        styles = STYLES.read_text(encoding="utf-8")
        roles = _declarations(styles, ":root")
        for selector in (
            ".button.primary",
            ".button.tonal",
            ".notice",
            ".notice.success",
            ".admin-feedback",
            ".admin-feedback.success",
            ".runtime-notice",
        ):
            values = _declarations(styles, selector)
            foreground = values["color"]
            background = values["background"]
            if foreground.startswith("var("):
                foreground = roles[foreground[4:-1]]
            if background.startswith("var("):
                background = roles[background[4:-1]]
            with self.subTest(selector=selector):
                assert _contrast(foreground, background) >= 4.5
        error = _declarations(styles, ".field-error")["color"]
        assert error == "var(--error)"
        assert _contrast(roles["--error"], roles["--surface"]) >= 4.5
