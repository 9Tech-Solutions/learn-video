"""Video-kind probe — classify before paying full vision cost.

Samples 5 frames spread across the video, asks one Flash Lite call:
"visual tutorial, audio-first (podcast/talking-head), or mixed?"

If audio-first → pipeline routes to :mod:`summary` (transcript-only path)
and skips targeting/keyframes/vision. Saves 5–50 LLM calls on podcasts and
long interviews where keyframes add no value.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import cache, config, logging_, model_client
from .errors import TransientError
from .ffmpeg_util import extract_frame
from .state import VideoKind

# Fractional positions across the video (avoid intro/outro).
_PROBE_FRACTIONS: tuple[float, ...] = (0.10, 0.30, 0.50, 0.70, 0.90)
_CACHE_SUBDIR = "probe"


class VideoKindClassification(BaseModel):
    kind: Literal["visual", "audio", "mixed"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)


_PROMPT = """You see {n} frames evenly sampled across a video.

Classify the video:
- "visual": meaningful teaching-on-screen — code, diagrams, UI demos, slides
- "audio": talking-head / podcast / interview / panel — static or irrelevant visuals
- "mixed": swings between both (e.g. conference talk with slides + Q&A)

Consider: if someone could get ~all the value from the transcript alone,
it's audio. If key moments depend on what's on screen, it's visual.

Return your best guess with a confidence 0.0-1.0 and a one-sentence reason.
"""


def _probe_frame_paths(paths: cache.CachePaths, duration_s: float) -> list[tuple[float, Path]]:
    out: list[tuple[float, Path]] = []
    subdir = paths.frames_dir / _CACHE_SUBDIR
    subdir.mkdir(parents=True, exist_ok=True)
    for frac in _PROBE_FRACTIONS:
        t = max(1.0, duration_s * frac)
        out.append((t, subdir / f"{frac:.2f}.jpg"))
    return out


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)

    # Cache check — reuse prior probe if present and not --fresh.
    meta = cache.read_meta(paths)
    if not state.get("fresh") and meta.get("video_kind"):
        logging_.info(
            f"probe cache hit → kind={meta['video_kind']} "
            f"conf={meta.get('video_kind_confidence', '?')}"
        )
        return {
            "video_kind": meta["video_kind"],
            "video_kind_confidence": float(meta.get("video_kind_confidence") or 0.0),
            "video_kind_reason": meta.get("video_kind_reason") or "",
            "probe_model_id": meta.get("probe_model_id") or "",
        }

    duration = float(state.get("duration_s") or 0.0)
    video_path = state.get("video_path")
    if not video_path or duration <= 0 or not Path(video_path).exists():
        # Without a video we can't probe; default to "mixed" so we still
        # try the full pipeline and don't silently skip content.
        return {
            "video_kind": "mixed",
            "video_kind_confidence": 0.0,
            "video_kind_reason": "probe skipped — no video file available",
            "probe_model_id": "",
        }

    frame_paths = _probe_frame_paths(paths, duration)
    for t, p in frame_paths:
        if not p.exists():
            extract_frame(Path(video_path), t, p)

    model_id = config.resolve_model_id(
        role="targeting",  # reuse the cheap tier for classification
        tier=state.get("tier", "lite"),
        offline=bool(state.get("offline")),
        model_override=None,
    )

    try:
        from langchain_core.messages import HumanMessage  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TransientError("langchain-core not installed") from exc

    content: list[dict[str, Any]] = [
        {"type": "text", "text": _PROMPT.format(n=len(frame_paths))},
    ]
    for t, p in frame_paths:
        content.append(
            {
                "type": "text",
                "text": f"Frame at t={t:.0f}s ({(t / duration) * 100:.0f}% through):",
            }
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{_b64(p)}"},
            }
        )

    model = model_client.tag_model(model_client.build_chat_model(model_id), model_id)
    with logging_.stage("PROBE", f"{model_id} classifying {len(frame_paths)} sample frames"):
        classification: VideoKindClassification = model_client.invoke_structured(
            model, VideoKindClassification, [HumanMessage(content=content)]
        )

    kind: VideoKind = classification.kind
    logging_.emit(
        "PROBE",
        f"→ {kind} (confidence {classification.confidence:.2f}) — {classification.reason}",
    )

    cache.update_meta(
        paths,
        video_kind=kind,
        video_kind_confidence=classification.confidence,
        video_kind_reason=classification.reason,
        probe_model_id=model_id,
    )
    return {
        "video_kind": kind,
        "video_kind_confidence": classification.confidence,
        "video_kind_reason": classification.reason,
        "probe_model_id": model_id,
    }
