"""Stage 5: vision-powered fusion.

Two entry points:

- :func:`per_frame_node`: one LLM call per ``FrameRef`` (default path).
- :func:`whole_video_node`: one File-API call for short videos (<60s on
  Gemini-capable tiers).
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import cache, config, logging_, model_client
from .errors import ConfigurationError
from .state import FrameRef, FusedBlock, VisionInput

# Concurrent frame requests. The sliding-window rate limiter in
# model_client enforces provider RPM caps; this just determines how many
# in-flight requests we're willing to juggle at once.
_VISION_MAX_CONCURRENCY = 6

_PER_FRAME_PROMPT = """You are fusing one frame of a video with its transcript window.

Return a single block in the shape:

VISUAL: <what is on screen: code, UI, diagram, etc. 1-2 sentences>
FUSED:  <what this frame teaches in context of the narration. 1-3 sentences,
        concrete and reusable as notes.>

Context follows.
"""

_WHOLE_VIDEO_PROMPT = """You are producing a tight timeline of a short video (<60s).

For each visually meaningful moment, output one block:

[mm:ss]
AUDIO:  <what is said, near-verbatim summary>
VISUAL: <what is on screen>
FUSED:  <1-2 sentence reusable note>

Cover 3-8 moments. Prefer signal over completeness.
"""


def _b64_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _extract_visual_and_fused(content: str) -> tuple[str | None, str]:
    """Minimal pull of VISUAL / FUSED lines from model output."""
    visual: str | None = None
    fused_parts: list[str] = []
    mode: str | None = None
    for line in (content or "").splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("VISUAL:"):
            visual = stripped.split(":", 1)[1].strip()
            mode = "visual"
        elif upper.startswith("FUSED:"):
            fused_parts.append(stripped.split(":", 1)[1].strip())
            mode = "fused"
        elif upper.startswith("AUDIO:"):
            mode = None  # we pull audio from the transcript_window instead
        elif stripped and mode == "fused":
            fused_parts.append(stripped)
    fused = " ".join(p for p in fused_parts if p).strip()
    if not fused:
        # Unparseable: keep the whole response as FUSED so nothing is silently lost.
        fused = (content or "").strip()
    return visual, fused


def per_frame_node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)
    frames: list[FrameRef] = list(state.get("frames") or [])

    if not frames:
        return {"fused_blocks": [], "vision_model_id": ""}

    model_id = config.resolve_model_id(
        role="vision",
        tier=state.get("tier", "lite"),
        offline=bool(state.get("offline")),
        model_override=state.get("model_override"),
    )
    model = model_client.tag_model(model_client.build_chat_model(model_id), model_id)

    def _fuse_one(ref: FrameRef) -> FusedBlock | None:
        img_path = Path(ref.image_path)
        if not img_path.exists():
            return None
        prompt = (
            f"{_PER_FRAME_PROMPT}\n"
            f"Timestamp: {ref.t:.1f}s\n"
            f"Transcript window:\n{ref.transcript_window}\n"
        )
        vi = VisionInput(text=prompt, image_b64=_b64_image(img_path))
        response = model_client.invoke_vision(model, vi, model_id=model_id)
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p)
                for p in content
            )
        visual, fused = _extract_visual_and_fused(str(content))
        return FusedBlock(t=ref.t, audio=ref.transcript_window, visual=visual, fused=fused)

    workers = max(1, min(_VISION_MAX_CONCURRENCY, len(frames)))
    blocks: list[FusedBlock] = []
    failures = 0
    with logging_.stage(
        "VISION",
        f"{model_id} fusing {len(frames)} frames ({workers}-way concurrent, rate-limited)",
    ), ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fuse_one, ref): ref for ref in frames}
        for fut in as_completed(futures):
            ref = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                failures += 1
                logging_.warn(
                    f"vision t={ref.t:.1f}s failed after retries: {exc}"
                )
                continue
            if result is not None:
                blocks.append(result)
    blocks.sort(key=lambda b: b.t)
    if failures:
        logging_.warn(
            f"{failures}/{len(frames)} vision calls failed, continuing with {len(blocks)} blocks"
        )

    cache.update_meta(paths, vision_model_id=model_id)
    return {"fused_blocks": blocks, "vision_model_id": model_id}


def whole_video_node(state: dict[str, Any]) -> dict[str, Any]:
    """Short-video fast path: single File API upload, single call."""
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)
    video_path = state.get("video_path")
    if not video_path:
        raise ConfigurationError("whole_video_node requires video_path in state")

    model_id = config.resolve_model_id(
        role="vision",
        tier=state.get("tier", "lite"),
        offline=bool(state.get("offline")),
        model_override=state.get("model_override"),
    )
    provider = model_id.split(":", 1)[0]
    if provider != "google_genai":
        raise ConfigurationError(
            f"short-video path requires a Gemini model; got {model_id}",
            fix_hint="use --tier=lite or --tier=pro",
        )

    model = model_client.tag_model(model_client.build_chat_model(model_id), model_id)
    vi = VisionInput(text=_WHOLE_VIDEO_PROMPT, video_path=video_path)

    with logging_.stage("VISION", f"{model_id} processing whole video (<60s)"):
        response = model_client.invoke_vision(model, vi, model_id=model_id)

    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )

    # Parse blocks from the model's timeline output.
    blocks: list[FusedBlock] = _parse_timeline(str(content))
    cache.update_meta(paths, vision_model_id=model_id, path="whole_video")
    return {"fused_blocks": blocks, "vision_model_id": model_id}


def _parse_timeline(text: str) -> list[FusedBlock]:
    """Parse `[mm:ss]` timeline blocks from the whole-video model response."""
    import re

    timecode_re = re.compile(r"^\s*\[(\d{1,2}):(\d{2})\]\s*$")
    blocks: list[FusedBlock] = []
    current_t: float | None = None
    audio: list[str] = []
    visual: list[str] = []
    fused: list[str] = []
    bucket: list[str] | None = None

    def flush() -> None:
        if current_t is None:
            return
        blocks.append(
            FusedBlock(
                t=current_t,
                audio=" ".join(audio).strip(),
                visual=" ".join(visual).strip() or None,
                fused=" ".join(fused).strip()
                or " ".join(audio + visual).strip(),
            )
        )

    for raw in text.splitlines():
        line = raw.strip()
        m = timecode_re.match(line)
        if m:
            if current_t is not None:
                flush()
            current_t = int(m.group(1)) * 60 + int(m.group(2))
            audio, visual, fused = [], [], []
            bucket = None
            continue
        upper = line.upper()
        if upper.startswith("AUDIO:"):
            bucket = audio
            audio.append(line.split(":", 1)[1].strip())
        elif upper.startswith("VISUAL:"):
            bucket = visual
            visual.append(line.split(":", 1)[1].strip())
        elif upper.startswith("FUSED:"):
            bucket = fused
            fused.append(line.split(":", 1)[1].strip())
        elif line and bucket is not None:
            bucket.append(line)
    if current_t is not None:
        flush()
    return blocks
