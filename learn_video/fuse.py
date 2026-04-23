"""Stage 6: compose the final timeline markdown from FusedBlocks.

No LLM here; vision.py did the per-frame fusion. This module orders blocks,
formats them as ``AUDIO / VISUAL / FUSED`` triads, and writes ``fused.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import cache, logging_
from .state import FusedBlock


def _mmss(seconds: float) -> str:
    s = int(max(0.0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def format_markdown(
    *,
    title: str | None,
    url: str,
    video_id: str,
    blocks: list[FusedBlock],
    targeting_model_id: str,
    vision_model_id: str,
    video_kind: str | None = None,
    video_kind_confidence: float | None = None,
    video_kind_reason: str | None = None,
    recommended_form: str | None = None,
    recommended_form_reason: str | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# {title or 'Video Notes'}")
    lines.append("")
    if recommended_form:
        reason = f", {recommended_form_reason}" if recommended_form_reason else ""
        lines.append(f"- **recommended-form:** `{recommended_form}`{reason}")
    if video_kind:
        conf = (
            f" (confidence {video_kind_confidence:.2f})"
            if isinstance(video_kind_confidence, (int, float))
            else ""
        )
        reason = f", {video_kind_reason}" if video_kind_reason else ""
        lines.append(f"- **video-kind:** `{video_kind}`{conf}{reason}")
    lines.append(f"- **URL:** {url}")
    lines.append(f"- **Video ID:** `{video_id}`")
    lines.append(f"- **Targeting model:** `{targeting_model_id}`")
    lines.append(f"- **Vision model:** `{vision_model_id}`")
    lines.append("")
    lines.append("## Timeline")
    lines.append("")

    if not blocks:
        lines.append("_No fused blocks produced._")
        lines.append("")
        return "\n".join(lines)

    for blk in sorted(blocks, key=lambda b: b.t):
        lines.append(f"### [{_mmss(blk.t)}]")
        lines.append("")
        if blk.audio:
            lines.append(f"**AUDIO:** {blk.audio}")
            lines.append("")
        if blk.visual:
            lines.append(f"**VISUAL:** {blk.visual}")
            lines.append("")
        if blk.fused:
            lines.append(f"**FUSED:** {blk.fused}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)

    blocks = list(state.get("fused_blocks") or [])
    md = format_markdown(
        title=state.get("title"),
        url=state.get("url", ""),
        video_id=video_id,
        blocks=blocks,
        targeting_model_id=state.get("targeting_model_id", ""),
        vision_model_id=state.get("vision_model_id", ""),
        video_kind=state.get("video_kind"),
        video_kind_confidence=state.get("video_kind_confidence"),
        video_kind_reason=state.get("video_kind_reason"),
        recommended_form=state.get("recommended_form"),
        recommended_form_reason=state.get("recommended_form_reason"),
    )

    with logging_.stage("FUSE", f"writing timeline → {paths.fused}"):
        paths.fused.write_text(md, encoding="utf-8")

    cache.update_meta(
        paths,
        final_md=str(paths.fused),
        targeting_model_id=state.get("targeting_model_id"),
        vision_model_id=state.get("vision_model_id"),
        block_count=len(blocks),
    )
    return {"final_md_path": str(paths.fused)}


def write_path(video_id: str) -> Path:
    """Expose the eventual output path without running the node."""
    return cache.paths_for(video_id).fused
