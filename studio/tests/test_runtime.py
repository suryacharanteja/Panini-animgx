# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009, PT027
"""Detect source updates before mixing a new page with old Python workers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import server


class RuntimeTests(unittest.TestCase):
    """Report a stale process and reject expensive jobs until it is restarted."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.application = server.Application(self.root / "data")
        self.addCleanup(
            self.application.executor.shutdown, wait=True, cancel_futures=True
        )

    def test_current_source_is_ready_without_probing_providers(self) -> None:
        with (
            patch.object(server, "source_revision", return_value="loaded"),
            patch.object(server, "LOADED_REVISION", "loaded"),
            patch.object(self.application.ollama, "models") as models,
        ):
            self.assertEqual(
                self.application.runtime(),
                {"protocol": 2, "restart_required": False},
            )
            models.assert_not_called()

    def test_changed_or_unreadable_sources_block_jobs_without_overwriting_data(
        self,
    ) -> None:
        for current in ("changed", None):
            with (
                self.subTest(current=current),
                patch.object(server, "source_revision", return_value=current),
                patch.object(server, "LOADED_REVISION", "loaded"),
                patch.object(self.application.executor, "submit") as submit,
            ):
                self.assertTrue(self.application.runtime()["restart_required"])
                for action in (
                    self.application.submit_plan,
                    self.application.submit_render,
                ):
                    with self.assertRaisesRegex(ValueError, "Ctrl.C.*panini.cmd"):
                        action({})
                submit.assert_not_called()
                self.assertFalse(self.application.jobs)
                self.assertFalse(self.application.directory.exists())

    def test_revision_reads_only_python_sources_not_project_data_or_preferences(
        self,
    ) -> None:
        source = self.root / "server.py"
        source.write_text("source = 1\n", encoding="utf-8")
        data = self.root / ".data"
        data.mkdir()
        project = data / "project.json"
        project.write_text('{"title":"original"}', encoding="utf-8")
        with patch.object(server, "SOURCE_ROOT", self.root):
            original = server.source_revision()
            project.write_text('{"title":"edited"}', encoding="utf-8")
            self.assertEqual(server.source_revision(), original)
            source.write_text("source = 2\n", encoding="utf-8")
            self.assertNotEqual(server.source_revision(), original)

    def test_unreadable_source_requires_restart_instead_of_claiming_ready(
        self,
    ) -> None:
        (self.root / "server.py").write_text("source = 1\n", encoding="utf-8")
        with (
            patch.object(server, "SOURCE_ROOT", self.root),
            patch.object(Path, "read_bytes", side_effect=OSError("unavailable")),
        ):
            self.assertIsNone(server.source_revision())
