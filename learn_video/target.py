"""Stage 3: LLM picks which timestamps need a visual frame.

For videos up to ``_SINGLE_PASS_MAX_S`` we call the LLM once on the whole
transcript. Longer videos get split into overlapping 15-minute windows and
targeted per-window; otherwise a 3-hour video would truncate at ~20 min
(Flash Lite context stays big but the 3–15 target budget doesn't scale).
"""

from __future__ import annotations

import json
from typing import Any

from . import cache, config, logging_, model_client
from .state import Target, TargetList

# Above this duration we switch to windowed targeting. 25 min lets most
# tutorials take the single-pass path; anything longer chunks.
_SINGLE_PASS_MAX_S = 25 * 60.0
_WINDOW_S = 15 * 60.0
_WINDOW_OVERLAP_S = 30.0
_TARGETS_PER_WINDOW_HINT = "3 to 10"
_SINGLE_PASS_TARGETS_HINT = "3 to 15 for a 20-minute video (scale linearly by length)"

_SYSTEM_PROMPT = """You are picking visual reference points from a video transcript.

Return a list of timestamps where seeing the screen matters for understanding: code
snippets, diagrams, UI demos, slides. Skip pure narration, talking-heads, b-roll.

Rules:
- {count_hint} targets
- timestamps in seconds from video start (not from this window)
- `why` in under 12 words: tell the vision model what to look for
- order by time ascending
- skip the first and last 5 seconds (titles/outros)
"""

_USER_SINGLE = """Video title: {title}
Duration: {duration_s:.1f}s

Transcript:
{transcript}
"""

_USER_WINDOW = """Video title: {title}
Total duration: {duration_s:.1f}s
This window: {w_start:.0f}s → {w_end:.0f}s (of {w_total} total windows)

Transcript for this window:
{transcript}
"""


def _load_segments(paths: cache.CachePaths) -> list[dict[str, Any]]:
    if not paths.transcript.exists():
        return []
    try:
        payload = json.loads(paths.transcript.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(payload.get("segments") or [])


def _segments_to_windows(
    segments: list[dict[str, Any]],
    duration_s: float,
) -> list[tuple[float, float, str]]:
    """Split segments into overlapping windows of ~15 min.

    Returns a list of (window_start_s, window_end_s, joined_text)."""
    if not segments:
        return [(0.0, duration_s, "")]
    windows: list[tuple[float, float, str]] = []
    w_start = 0.0
    while w_start < duration_s:
        w_end = min(duration_s, w_start + _WINDOW_S)
        lo = max(0.0, w_start - _WINDOW_OVERLAP_S)
        hi = min(duration_s, w_end + _WINDOW_OVERLAP_S)
        pieces: list[str] = []
        for seg in segments:
            s = float(seg.get("start", 0.0))
            if s < lo or s > hi:
                continue
            mm = int(s // 60)
            ss = int(s % 60)
            text = (seg.get("text") or "").strip()
            if text:
                pieces.append(f"[{mm:02d}:{ss:02d}] {text}")
        if pieces:
            windows.append((w_start, w_end, "\n".join(pieces)))
        w_start += _WINDOW_S
    return windows or [(0.0, duration_s, "")]


def _build_single_pass_messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": _SYSTEM_PROMPT.format(count_hint=_SINGLE_PASS_TARGETS_HINT),
        },
        {
            "role": "user",
            "content": _USER_SINGLE.format(
                title=state.get("title") or "(untitled)",
                duration_s=state.get("duration_s") or 0.0,
                transcript=(state.get("transcript") or "")[:30_000],
            ),
        },
    ]


def _build_window_messages(
    state: dict[str, Any],
    w_start: float,
    w_end: float,
    w_total: int,
    window_text: str,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": _SYSTEM_PROMPT.format(count_hint=_TARGETS_PER_WINDOW_HINT),
        },
        {
            "role": "user",
            "content": _USER_WINDOW.format(
                title=state.get("title") or "(untitled)",
                duration_s=state.get("duration_s") or 0.0,
                w_start=w_start,
                w_end=w_end,
                w_total=w_total,
                transcript=window_text[:40_000],
            ),
        },
    ]


def _filter_targets(targets: list[Target], duration_s: float) -> list[Target]:
    """Drop out-of-bounds timestamps and near-duplicates."""
    if duration_s <= 0:
        return targets
    clean: list[Target] = []
    last_t = -1e9
    for t in sorted(targets, key=lambda x: x.t):
        if t.t < 5.0 or t.t > max(0.0, duration_s - 5.0):
            continue
        if t.t - last_t < 2.0:  # collapse near-identical timestamps
            continue
        clean.append(t)
        last_t = t.t
    return clean


def node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)

    # Cache hit
    if paths.targets.exists() and not state.get("fresh"):
        try:
            payload = json.loads(paths.targets.read_text(encoding="utf-8"))
            targets = [Target.model_validate(t) for t in payload.get("targets", [])]
            if targets:
                logging_.emit("TARGETING", f"cache hit ({len(targets)} targets)")
                return {
                    "targets": targets,
                    "targeting_model_id": payload.get("model_id", ""),
                }
        except Exception:
            pass

    model_id = config.resolve_model_id(
        role="targeting",
        tier=state.get("tier", "lite"),
        offline=bool(state.get("offline")),
        model_override=None,  # --model applies to vision only
    )
    model = model_client.tag_model(model_client.build_chat_model(model_id), model_id)

    duration_s = float(state.get("duration_s") or 0.0)
    raw_targets: list[Target] = []

    if duration_s <= _SINGLE_PASS_MAX_S:
        with logging_.stage("TARGETING", f"{model_id} reading transcript (single pass)"):
            result: TargetList = model_client.invoke_structured(
                model, TargetList, _build_single_pass_messages(state)
            )
            raw_targets = list(result.targets)
    else:
        segments = _load_segments(paths)
        windows = _segments_to_windows(segments, duration_s)
        with logging_.stage(
            "TARGETING",
            f"{model_id} windowed read, {len(windows)} × 15-min passes",
        ):
            for i, (ws, we, wtext) in enumerate(windows, start=1):
                if not wtext:
                    continue
                logging_.emit(
                    "TARGETING",
                    f"window {i}/{len(windows)}: {int(ws)}s → {int(we)}s",
                )
                try:
                    res: TargetList = model_client.invoke_structured(
                        model,
                        TargetList,
                        _build_window_messages(state, ws, we, len(windows), wtext),
                    )
                except Exception as exc:
                    # A single bad window shouldn't tank the whole run;
                    # downstream stages can absorb a lighter target list.
                    logging_.warn(
                        f"targeting window {i}/{len(windows)} failed: {exc}"
                    )
                    continue
                # Filter per-window to the window's own range so the model
                # can't invent offsets outside it.
                for t in res.targets:
                    if ws <= t.t <= we:
                        raw_targets.append(t)

    targets = _filter_targets(raw_targets, duration_s)
    logging_.emit("TARGETING", f"kept {len(targets)} targets (after filtering)")

    paths.targets.write_text(
        json.dumps(
            {
                "model_id": model_id,
                "targets": [t.model_dump() for t in targets],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    cache.update_meta(paths, targeting_model_id=model_id, target_count=len(targets))
    return {"targets": targets, "targeting_model_id": model_id}
