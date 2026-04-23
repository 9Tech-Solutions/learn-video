#!/usr/bin/env bash
# learn-video: shim that delegates to scripts/install.py.
# The real installer is in Python so Windows PowerShell, macOS, Linux,
# and git-bash all run the same codepath.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: Python 3.11+ not found. Install it and retry." >&2
    exit 1
fi

exec "$PYTHON_BIN" "$REPO_ROOT/scripts/install.py" "$@"
