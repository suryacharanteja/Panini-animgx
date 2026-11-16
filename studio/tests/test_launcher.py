# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009, PT027
"""Exercise one-command startup without opening browsers or leaving servers running."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import webbrowser
from pathlib import Path
from unittest.mock import patch

from studio import server

REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "panini.cmd"


class BrowserLaunchTests(unittest.TestCase):
    """Only launch the browser after the local server successfully binds."""

    def test_open_uses_bound_port_before_serving_and_stops_cleanly(self) -> None:
        events: list[str] = []
        with (
            patch.object(sys, "argv", ["studio.server", "--open", "--port", "7861"]),
            patch.object(server, "Application") as application_type,
            patch.object(server, "StudioServer", autospec=True) as server_type,
            patch("studio.server.webbrowser.open") as open_browser,
            patch("builtins.print"),
        ):
            application = application_type.return_value
            local_server = server_type.return_value
            local_server.server_port = 8765
            local_server.server_address = ("127.0.0.1", 8765)

            def bound() -> object:
                events.append("bound")
                return local_server

            def browse(url: str, *, new: int) -> bool:
                self.assertEqual(url, "http://127.0.0.1:8765")
                self.assertEqual(new, 2)
                events.append("browser")
                return True

            def serve() -> None:
                events.append("serving")
                raise KeyboardInterrupt

            server_type.return_value.__enter__.side_effect = bound
            open_browser.side_effect = browse
            local_server.serve_forever.side_effect = serve
            server.main()
            server_type.assert_called_once_with(("127.0.0.1", 7861), application)
            self.assertEqual(events, ["bound", "browser", "serving"])
            application.executor.shutdown.assert_called_once_with(
                wait=True, cancel_futures=True
            )

    def test_browser_is_opt_in_and_no_open_overrides_launcher_default(self) -> None:
        for arguments in ([], ["--open", "--no-open"]):
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["studio.server", *arguments]),
                patch.object(server, "Application"),
                patch.object(server, "StudioServer", autospec=True) as server_type,
                patch("studio.server.webbrowser.open") as open_browser,
                patch("builtins.print"),
            ):
                local_server = server_type.return_value
                local_server.server_port = 7860
                local_server.server_address = ("127.0.0.1", 7860)
                local_server.serve_forever.side_effect = KeyboardInterrupt
                server.main()
                open_browser.assert_not_called()
                local_server.serve_forever.assert_called_once()

    def test_browser_errors_leave_the_server_available_for_manual_open(self) -> None:
        for failure in (webbrowser.Error("No browser found"), OSError("Unavailable")):
            with (
                self.subTest(failure=type(failure).__name__),
                patch.object(sys, "argv", ["studio.server", "--open"]),
                patch.object(server, "Application"),
                patch.object(server, "StudioServer", autospec=True) as server_type,
                patch("studio.server.webbrowser.open", side_effect=failure),
                patch("builtins.print") as report,
            ):
                local_server = server_type.return_value
                local_server.server_port = 7860
                local_server.server_address = ("127.0.0.1", 7860)
                local_server.serve_forever.side_effect = KeyboardInterrupt
                server.main()
                local_server.serve_forever.assert_called_once()
                self.assertTrue(
                    any(
                        "http://127.0.0.1:7860" in str(call)
                        and "browser" in str(call).lower()
                        for call in report.call_args_list
                    )
                )

    def test_failed_bind_does_not_open_browser_or_leave_executor_alive(self) -> None:
        with (
            patch.object(sys, "argv", ["studio.server", "--open"]),
            patch.object(server, "Application") as application_type,
            patch.object(
                server, "StudioServer", autospec=True, side_effect=OSError("Port busy")
            ),
            patch("studio.server.webbrowser.open") as open_browser,
            patch("sys.stderr.write") as report,
            self.assertRaises(SystemExit) as exit_context,
        ):
            server.main()
        self.assertEqual(exit_context.exception.code, 1)
        open_browser.assert_not_called()
        application_type.return_value.executor.shutdown.assert_called_once_with(
            wait=False, cancel_futures=True
        )
        self.assertTrue(any("--port" in str(call) for call in report.call_args_list))

    def test_browser_declining_to_open_preserves_manual_access(self) -> None:
        with (
            patch.object(sys, "argv", ["studio.server", "--open"]),
            patch.object(server, "Application"),
            patch.object(server, "StudioServer", autospec=True) as server_type,
            patch("studio.server.webbrowser.open", return_value=False),
            patch("builtins.print") as report,
        ):
            local_server = server_type.return_value
            local_server.server_address = ("127.0.0.1", 7860)
            local_server.serve_forever.side_effect = KeyboardInterrupt
            server.main()
            local_server.serve_forever.assert_called_once()
            self.assertTrue(
                any(
                    "Open http://127.0.0.1:7860" in str(call)
                    for call in report.call_args_list
                )
            )

    def test_invalid_ports_fail_before_creating_resources(self) -> None:
        for arguments in (
            ["--port", "0"],
            ["--port", "65536"],
            ["--ollama-port", "0"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(sys, "argv", ["studio.server", "--open", *arguments]),
                patch.object(server, "Application") as application_type,
                patch("studio.server.webbrowser.open") as open_browser,
                patch("sys.stderr.write"),
                self.assertRaises(SystemExit) as exit_context,
            ):
                server.main()
            self.assertEqual(exit_context.exception.code, 2)
            application_type.assert_not_called()
            open_browser.assert_not_called()


@unittest.skipUnless(os.name == "nt", "The terminal launcher targets Windows")
class TerminalLauncherTests(unittest.TestCase):
    """Run the batch launcher with isolated prerequisites and a harmless uv shim."""

    def setUp(self) -> None:
        temporary_root = (
            REPOSITORY / "studio" / ".data" / "tests" / "launcher-workspaces"
        )
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="panini launcher ", dir=temporary_root
        )
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name) / "repo with spaces"
        self.workspace.mkdir()
        self.launcher = self.workspace / "panini.cmd"
        shutil.copyfile(LAUNCHER, self.launcher)
        self.other_directory = Path(self.temporary.name) / "elsewhere"
        self.other_directory.mkdir()
        self.system_directory = Path(os.environ["SystemRoot"]) / "System32"
        self.environment = os.environ.copy()
        self.environment["PATH"] = str(self.system_directory)
        self.environment.pop("UV_CACHE_DIR", None)

    def run_launcher(
        self, arguments: tuple[str, ...] = ()
    ) -> subprocess.CompletedProcess[str]:
        """Start the isolated launcher from a different working directory."""
        return subprocess.run(
            [
                str(self.system_directory / "cmd.exe"),
                "/d",
                "/c",
                "call",
                str(self.launcher),
                *arguments,
            ],
            cwd=self.other_directory,
            env=self.environment,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    def install_uv_shim(self) -> Path:
        """Capture uv's arguments and environment without starting Python."""
        tools_directory = Path(self.temporary.name) / "fake tools"
        tools_directory.mkdir()
        log = Path(self.temporary.name) / "invocation.txt"
        (tools_directory / "uv.cmd").write_text(
            '@echo off\n> "%PANINI_TEST_LOG%" (\n'
            "echo cwd=%CD%\n"
            "echo cache=%UV_CACHE_DIR%\n"
            "echo args=%*\n"
            ")\nexit /b 23\n",
            encoding="utf-8",
        )
        self.environment["PATH"] = (
            str(tools_directory) + os.pathsep + str(self.system_directory)
        )
        self.environment["PANINI_TEST_LOG"] = str(log)
        return log

    def install_venv_marker(self) -> None:
        """Create only the preflight marker; the uv shim does not execute it."""
        interpreter = self.workspace / ".venv" / "Scripts" / "python.exe"
        interpreter.parent.mkdir(parents=True)
        interpreter.touch()

    def test_missing_uv_has_actionable_diagnostic_and_failure_status(self) -> None:
        self.install_venv_marker()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        message = (result.stdout + result.stderr).lower()
        self.assertIn("uv", message)
        self.assertTrue("install" in message or "path" in message)

    def test_missing_environment_does_not_attempt_an_implicit_install(self) -> None:
        log = self.install_uv_shim()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        message = (result.stdout + result.stderr).lower()
        self.assertIn("environment", message)
        self.assertTrue("setup" in message or "sync" in message)
        self.assertFalse(log.exists())

    def test_forwards_arguments_uses_repo_directory_and_propagates_exit_status(
        self,
    ) -> None:
        log = self.install_uv_shim()
        self.install_venv_marker()
        result = self.run_launcher(("--port", "7861", "--no-open", "--help"))
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        invocation = log.read_text(encoding="utf-8")
        self.assertIn(f"cwd={self.workspace}", invocation)
        self.assertIn(f"cache={self.workspace / '.uv-cache'}", invocation)
        self.assertIn(
            "args=run --frozen --no-sync python -m studio.server --open "
            "--port 7861 --no-open --help",
            invocation,
        )

    @unittest.skipUnless(
        shutil.which("uv")
        and (REPOSITORY / ".venv" / "Scripts" / "python.exe").is_file(),
        "The real launch smoke test requires the existing uv environment",
    )
    def test_real_launcher_help_from_another_directory_never_opens_browser(
        self,
    ) -> None:
        self.launcher = LAUNCHER
        self.environment = os.environ.copy()
        result = self.run_launcher(("--help",))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--port", result.stdout)
        self.assertIn("--open", result.stdout)
        self.assertIn("--no-open", result.stdout)
        self.assertNotIn("Panini-Animgx Studio: http://", result.stdout)
