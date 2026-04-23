"""Tiny ffmpeg wrapper shared by keyframes and probe stages."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import EnvironmentError_, TransientError


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise EnvironmentError_(
            "ffmpeg not found on PATH",
            install_cmd="choco install ffmpeg  # or apt install ffmpeg",
        )
    return path


def extract_frame(video_path: Path, t: float, out_path: Path) -> None:
    """Grab one JPEG frame at ``t`` seconds. Fast-seek mode (``-ss`` before ``-i``)."""
    ffmpeg = require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss", f"{t:.2f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "4",
            "-loglevel", "error",
            str(out_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or not out_path.exists():
        raise TransientError(
            f"ffmpeg frame extraction failed at t={t}: {proc.stderr.strip()}"
        )
