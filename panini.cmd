@echo off
rem SPDX-FileCopyrightText: 2026 ndimensions.AI
rem SPDX-License-Identifier: MIT
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

where uv >nul 2>nul
if errorlevel 1 goto missing_uv
if not exist ".venv\Scripts\python.exe" goto missing_environment

set "UV_CACHE_DIR=%CD%\.uv-cache"
call uv run --frozen --no-sync python -m studio.server --open %*
set "PANINI_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %PANINI_EXIT_CODE%

:missing_uv
echo Studio needs uv on PATH. Install uv and follow the setup guide in studio\README.md.
popd
exit /b 1

:missing_environment
echo Studio's environment is missing. Follow the setup guide in studio\README.md and run uv sync first.
popd
exit /b 1
