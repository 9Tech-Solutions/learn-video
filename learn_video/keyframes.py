"""Stage 4: ffmpeg extracts one keyframe per targeted timestamp.

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
        logging_.warn("no targets; skipping keyframes")
        return {"frames": []}

    video_path_str = state.get("video_path")
    video_path = Path(video_path_str) if video_path_str else None
    fresh = bool(state.get("fresh"))
    # The video is only needed for frames that are not already on disk. After
    # `prune` it is gone, but every frame from the previous run still exists.
    missing = [t for t in targets if fresh or not paths.frame(t.t).exists()]
    if missing and (video_path is None or not video_path.exists()):
        raise TransientError(
            f"keyframes stage needs the video for {len(missing)} frame(s) but the "
            "media was pruned, re-run with --fresh to download again"
        )

    segments = _load_segments(paths)

    refs: list[FrameRef] = []
    with logging_.stage("KEYFRAMES", f"extracting {len(missing)} of {len(targets)} frames via ffmpeg"):
        for target in targets:
            frame_path = paths.frame(target.t)
            # video_path is None only when nothing is missing (checked above)
            if (not frame_path.exists() or fresh) and video_path is not None:
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
