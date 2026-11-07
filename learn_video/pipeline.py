"""LangGraph StateGraph: the narrow orchestrator.

Graph shape:

    START → ingest → transcribe ─┬─► agy_watch ─► fuse ─► prune ─► END   (engine=agy: agy on PATH, no API key)
                                 └─► probe_short                          (engine=api)
      ├─► whole_video_oneshot ─► classify ─► fuse ─► END    (short, Gemini-capable tier)
      └─► probe_kind
            ├─► summary ─► classify ─► fuse ─► prune ─► END          (audio-first: podcast/talk)
            └─► target ─► keyframes ─► vision ─► classify ─► fuse ─► prune ─► END  (visual path)

`prune` deletes the downloaded media once fused.md exists (unless
--keep-video). Every other artifact stays, so re-runs are free.
"""

from __future__ import annotations

from typing import Any

from . import agy, cache, ingest, keyframes, logging_, probe, summary, target, transcribe, vision
from . import classify as classify_stage
from . import fuse as fuse_stage
from .config import SHORT_PATH_TIERS
from .errors import ConfigurationError
from .state import PipelineState

_AUDIO_KIND_CONFIDENCE = 0.65  # below this we err on the safe side and go visual


def _prune_node(state: PipelineState) -> dict[str, Any]:
    """Drop video + raw captions after a successful fuse. ~99% of the cache bytes."""
    if state.get("keep_video"):
        logging_.info("--keep-video set, media kept in cache")
        return {}
    paths = cache.paths_for(state["video_id"])
    if not paths.fused.exists():
        return {}
    freed = cache.prune_media(paths)
    if freed:
        logging_.emit("PRUNE", f"removed media, freed {freed / (1024 * 1024):.1f} MB")
    return {"video_path": None}


def _engine_router(state: PipelineState) -> str:
    """agy watches the whole video when the CLI picked it; otherwise the API stages run."""
    return "agy_watch" if state.get("engine") == "agy" else "probe_short"


def _probe_short_router(state: PipelineState) -> str:
    if (
        state.get("is_short_video")
        and state.get("tier") in SHORT_PATH_TIERS
        and not state.get("offline")
    ):
        return "whole_video_oneshot"
    return "probe_kind"


def _probe_short_node(state: PipelineState) -> dict[str, Any]:
    """No-op passthrough: exists purely to anchor the conditional edge."""
    force_short = bool(state.get("force_short"))
    duration = state.get("duration_s") or 0.0
    if force_short and duration and duration > 60.0:
        raise ConfigurationError(
            f"--short requires video < 60s. Actual: {duration:.0f}s.",
            fix_hint="drop --short or pick a shorter clip",
        )
    return {}


def _kind_router(state: PipelineState) -> str:
    kind = state.get("video_kind")
    conf = float(state.get("video_kind_confidence") or 0.0)
    if kind == "audio" and conf >= _AUDIO_KIND_CONFIDENCE:
        return "summary"
    return "target"


def build_graph():
    """Construct and compile the StateGraph."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise ConfigurationError(
            "langgraph not installed",
            fix_hint="pip install -r ~/.claude/scripts/learn_video/requirements.txt",
        ) from exc

    g: Any = StateGraph(PipelineState)
    g.add_node("ingest", ingest.node)
    g.add_node("transcribe", transcribe.node)
    g.add_node("agy_watch", agy.node)
    g.add_node("probe_short", _probe_short_node)
    g.add_node("probe_kind", probe.node)
    g.add_node("whole_video_oneshot", vision.whole_video_node)
    g.add_node("summary", summary.node)
    g.add_node("target", target.node)
    g.add_node("keyframes", keyframes.node)
    g.add_node("vision", vision.per_frame_node)
    g.add_node("classify", classify_stage.node)
    g.add_node("fuse", fuse_stage.node)
    g.add_node("prune", _prune_node)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "transcribe")
    g.add_conditional_edges(
        "transcribe",
        _engine_router,
        {"agy_watch": "agy_watch", "probe_short": "probe_short"},
    )
    g.add_edge("agy_watch", "fuse")
    g.add_conditional_edges(
        "probe_short",
        _probe_short_router,
        {
            "whole_video_oneshot": "whole_video_oneshot",
            "probe_kind": "probe_kind",
        },
    )
    g.add_conditional_edges(
        "probe_kind",
        _kind_router,
        {"summary": "summary", "target": "target"},
    )
    g.add_edge("whole_video_oneshot", "classify")
    g.add_edge("summary", "classify")
    g.add_edge("target", "keyframes")
    g.add_edge("keyframes", "vision")
    g.add_edge("vision", "classify")
    g.add_edge("classify", "fuse")
    g.add_edge("fuse", "prune")
    g.add_edge("prune", END)

    return g.compile()


def run(initial: PipelineState) -> PipelineState:
    graph = build_graph()
    logging_.info(
        f"running pipeline engine={initial.get('engine', 'api')} tier={initial.get('tier', 'lite')} "
        f"offline={bool(initial.get('offline'))} url={initial.get('url')}"
    )
    return graph.invoke(initial)
