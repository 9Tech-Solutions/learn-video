#!/usr/bin/env pwsh
# learn-video — PowerShell shim that delegates to scripts/install.py.
#
# If you see an execution-policy error, run this once in the current shell:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }

try {
    & $Python --version | Out-Null
} catch {
    Write-Error "Python 3.11+ not found on PATH. Install it and retry."
    exit 1
}

& $Python "$RepoRoot/scripts/install.py" @args
exit $LASTEXITCODE
