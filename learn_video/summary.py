"""Transcript-only summary path — used when probe_kind says "audio".

Replaces target → keyframes → vision for podcasts, interviews, and
talking-head videos. One LLM call that chunks the transcript into topical
blocks with timestamps. Output feeds the same :mod:`fuse` node as the
visual path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from . import cache, config, logging_, model_client
from .state import FusedBlock

# Max transcript chars sent to the model — Flash Lite handles ~1M tokens but
# trimming keeps latency reasonable. ~50k chars ≈ ~45 min of dense speech.
_TRANSCRIPT_CHAR_CAP = 50_000


class Chapter(BaseModel):
    t_start: float = Field(ge=0.0)
    t_end: float = Field(ge=0.0)
    topic: str = Field(min_length=1)
    key_points: list[str]


class ChapterList(BaseModel):
    chapters: list[Chapter]


_SYSTEM_PROMPT = """You are summarizing a transcript into chapters of a talk, podcast, or interview.

For each chapter return:
- t_start, t_end (seconds from video start — use transcript timestamps)
- topic (5–12 words, specific not generic)
- key_points (2–5 items, each a complete sentence conveying a reusable insight)

Scale chapter count with length: 3–6 chapters for ≤30 min, 6–12 for 30–90 min,
10–20 for longer. Group by topic shift, not by fixed interval.

Skip intros, outros, sponsor reads, and filler.
"""

_USER_TEMPLATE = """Title: {title}
Duration: {duration_s:.0f}s

Transcript (with timestamps):
{transcript_with_ts}
"""


def _load_segments(paths: cache.CachePaths) -> list[dict[str, Any]]:
    if not paths.transcript.exists():
        return []
    try:
        payload = json.loads(paths.transcript.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(payload.get("segments") or [])


def _format_with_timestamps(segments: list[dict[str, Any]]) -> str:
    """One line per segment, prefixed with [mm:ss] — gives the model hard
    timestamps to cite instead of guessing."""
    lines: list[str] = []
    total = 0
    for seg in segments:
        t = float(seg.get("start", 0.0))
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        mm = int(t // 60)
        ss = int(t % 60)
        line = f"[{mm:02d}:{ss:02d}] {text}"
        if total + len(line) > _TRANSCRIPT_CHAR_CAP:
            lines.append("[...truncated...]")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines)


def _to_fused_blocks(chapters: list[Chapter]) -> list[FusedBlock]:
    blocks: list[FusedBlock] = []
    for ch in chapters:
        fused_text = " ".join(p.strip() for p in ch.key_points if p.strip())
        blocks.append(
            FusedBlock(
                t=ch.t_start,
                audio=ch.topic,
                visual=None,
                fused=fused_text or ch.topic,
            )
        )
    return blocks


def node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)

    # Cache via fused_blocks field in targets.json-adjacent slot: store in
    # meta, reuse on non-fresh reruns.
    meta = cache.read_meta(paths)
    if not state.get("fresh") and meta.get("summary_blocks"):
        blocks = [FusedBlock.model_validate(b) for b in meta["summary_blocks"]]
        logging_.info(f"summary cache hit ({len(blocks)} chapters)")
        return {"fused_blocks": blocks, "vision_model_id": meta.get("summary_model_id", "")}

    segments = _load_segments(paths)
    if not segments:
        logging_.warn("summary path: no segments — emitting one catch-all block")
        return {
            "fused_blocks": [
                FusedBlock(
                    t=0.0,
                    audio="(no transcript segments)",
                    fused=(state.get("transcript") or "")[:500],
                )
            ],
            "vision_model_id": "",
        }

    model_id = config.resolve_model_id(
        role="targeting",  # reuse cheap tier — this is text-only
        tier=state.get("tier", "lite"),
        offline=bool(state.get("offline")),
        model_override=None,
    )
    model = model_client.tag_model(model_client.build_chat_model(model_id), model_id)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(
                title=state.get("title") or "(untitled)",
                duration_s=state.get("duration_s") or 0.0,
                transcript_with_ts=_format_with_timestamps(segments),
            ),
        },
    ]

    with logging_.stage("SUMMARY", f"{model_id} chaptering transcript"):
        result: ChapterList = model_client.invoke_structured(model, ChapterList, messages)

    blocks = _to_fused_blocks(result.chapters)
    logging_.emit("SUMMARY", f"{len(blocks)} chapters produced")

    cache.update_meta(
        paths,
        summary_blocks=[b.model_dump() for b in blocks],
        summary_model_id=model_id,
    )
    return {"fused_blocks": blocks, "vision_model_id": model_id}
