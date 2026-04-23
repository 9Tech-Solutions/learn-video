"""Progress reporting — `[N/6 STAGE]` lines on stderr.

Stdout is reserved for the final fused.md path so the slash command can
capture just the artifact.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Iterator

STAGES: tuple[str, ...] = (
    "INGEST",
    "TRANSCRIBE",
    "TARGETING",
    "KEYFRAMES",
    "VISION",
    "FUSE",
)


def emit(stage: str, message: str) -> None:
    """Write a `[N/6 STAGE] message` line to stderr."""
    try:
        idx = STAGES.index(stage.upper())
    except ValueError:
        idx = -1
    prefix = f"[{idx + 1}/{len(STAGES)} {stage.upper()}]" if idx >= 0 else f"[{stage}]"
    print(f"{prefix} {message}", file=sys.stderr, flush=True)


@contextmanager
def stage(stage_name: str, message: str) -> Iterator[None]:
    """Emit a stage line, then yield. On exit prints elapsed time if >0.5s."""
    emit(stage_name, message)
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        if elapsed >= 0.5:
            emit(stage_name, f"done ({elapsed:.1f}s)")


def info(message: str) -> None:
    print(f"[info] {message}", file=sys.stderr, flush=True)


def warn(message: str) -> None:
    print(f"[warn] {message}", file=sys.stderr, flush=True)


def fatal(message: str, *, fix_hint: str | None = None) -> None:
    print(f"[FATAL] {message}", file=sys.stderr, flush=True)
    if fix_hint:
        print(f"        {fix_hint}", file=sys.stderr, flush=True)
