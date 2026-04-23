"""Stage 4 — ffmpeg extracts one keyframe per targeted timestamp.

Pure Python, no LLM. Uses ``ffmpeg -ss <t> -i <video> -frames:v 1 <out.jpg>``.
The transcript_window attached to each frame is a ±10s snippet around the
timestamp so the vision stage has context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import cache, logging_
from .errors import TransientError
from .ffmpeg_util import extract_frame
from .state import FrameRef, Target

_WINDOW_S = 10.0


def _transcript_window(segments: list[dict[str, Any]], t: float) -> str:
    lo, hi = t - _WINDOW_S, t + _WINDOW_S
    pieces: list[str] = []
    for seg in segments:
        s = float(seg.get("start", 0.0))
        e = float(seg.get("end", s))
        if e < lo or s > hi:
            continue
        text = seg.get("text", "").strip()
        if text:
            pieces.append(text)
    return " ".join(pieces).strip()


def _load_segments(paths: cache.CachePaths) -> list[dict[str, Any]]:
    if not paths.transcript.exists():
        return []
    try:
        payload = json.loads(paths.transcript.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(payload.get("segments") or [])


def node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)

    targets: list[Target] = list(state.get("targets") or [])
    if not targets:
        logging_.warn("no targets — skipping keyframes")
        return {"frames": []}

    video_path_str = state.get("video_path")
    if not video_path_str or not Path(video_path_str).exists():
        raise TransientError("keyframes stage needs video_path, none found")
    video_path = Path(video_path_str)

    segments = _load_segments(paths)

    refs: list[FrameRef] = []
    with logging_.stage("KEYFRAMES", f"extracting {len(targets)} frames via ffmpeg"):
        for target in targets:
            frame_path = paths.frame(target.t)
            if not frame_path.exists() or state.get("fresh"):
                extract_frame(video_path, target.t, frame_path)
            window = _transcript_window(segments, target.t)
            refs.append(
                FrameRef(
                    t=target.t,
                    image_path=str(frame_path),
                    transcript_window=window,
                )
            )
    return {"frames": refs}
