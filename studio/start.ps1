# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
# Start from any working directory using this checkout's existing environment.
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
uv run --frozen --no-sync python -m studio.server --open @args
exit $LASTEXITCODE
