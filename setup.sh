#!/usr/bin/env bash
# learn-video — one-shot local setup.
# Creates a venv, installs pinned requirements, and prints next steps.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: Python not found. Install Python 3.11+ and retry." >&2
    exit 1
fi

echo "==> Python: $("$PYTHON_BIN" --version)"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "WARN: ffmpeg not found on PATH. Install it before running learn-video:" >&2
    echo "       macOS:   brew install ffmpeg" >&2
    echo "       Linux:   apt install ffmpeg" >&2
    echo "       Windows: choco install ffmpeg" >&2
fi

VENV="$REPO_ROOT/.venv"
if [ ! -d "$VENV" ]; then
    echo "==> Creating virtualenv at .venv/"
    "$PYTHON_BIN" -m venv "$VENV"
fi

# shellcheck disable=SC1091
if [ -f "$VENV/bin/activate" ]; then
    source "$VENV/bin/activate"
elif [ -f "$VENV/Scripts/activate" ]; then
    source "$VENV/Scripts/activate"
else
    echo "ERROR: venv activate script not found." >&2
    exit 1
fi

echo "==> Upgrading pip"
python -m pip install --quiet --upgrade pip

echo "==> Installing requirements (this pulls ~350 MB: langgraph + langchain + provider SDKs + whisper)"
python -m pip install -r requirements.txt

echo
echo "=============================================================="
echo "Setup complete."
echo
echo "Next steps:"
echo "  1. Copy .env.example to .env and set GEMINI_API_KEY"
echo "       cp .env.example .env && \$EDITOR .env"
echo
echo "  2. Activate the venv in new shells:"
echo "       source $VENV/bin/activate   # or .venv/Scripts/activate on Windows"
echo
echo "  3. Try it:"
echo "       python -m learn_video.cli run \"https://www.youtube.com/watch?v=<id>\""
echo
echo "  4. (optional) Install as a Claude Code skill:"
echo "       cp commands/learn-video.md ~/.claude/commands/"
echo "       cp -r learn_video ~/.claude/scripts/"
echo "=============================================================="
