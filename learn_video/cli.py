"""CLI entry point: `python -m learn_video.cli <subcommand> [args]`.

Subcommands:
  run <url>        : execute the 6-stage pipeline (default)
  cache-info       : list cached video-ids, sizes, last-used
  cache-clean ID   : delete one cache dir (or `all`)
  cache-prune      : delete media from every cache dir, keep notes/transcripts
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path
from typing import cast

from . import cache, config, logging_
from .errors import (
    ConfigurationError,
    EnvironmentError_,
    LearnVideoError,
    TargetError,
    TransientError,
)
from .state import PipelineState


def _maybe_load_dotenv() -> None:
    """Load `~/.claude/scripts/learn_video/.env` if python-dotenv is installed."""
    env_path = Path.home() / ".claude" / "scripts" / "learn_video" / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(env_path, override=False)


def _default_gemini_api_version() -> None:
    """google-genai 3.x calls the v1 API by default, where the `-latest` tier aliases 404.

    They exist only on v1beta, so default to it. An explicit GOOGLE_GENAI_API_VERSION wins.
    """
    os.environ.setdefault("GOOGLE_GENAI_API_VERSION", "v1beta")


def _pick_engine(args: argparse.Namespace) -> str:
    """agy first. An explicit provider choice (--tier, --model, --offline, --no-agy) means the API stages."""
    from . import agy

    if args.no_agy or args.offline or args.model or args.tier:
        return "api"
    if agy.find_agy():
        return "agy"
    logging_.info("agy not found on PATH, using the API stages")
    return "api"


def _require_api_keys(state: PipelineState, loaded: config.LoadedConfig) -> None:
    """Fail before any download when the API route has no key, so the caller can ask for one."""
    from . import model_client

    if state["engine"] != "api" or state["offline"]:
        return
    for role in ("targeting", "vision"):
        model_id = config.resolve_model_id(
            role=role, tier=state["tier"], offline=False,
            model_override=state["model_override"], loaded=loaded,
        )
        try:
            model_client.verify_api_key(model_id)
        except ConfigurationError as exc:
            raise ConfigurationError(
                f"NO_AGY_NO_API_KEY: agy is not on PATH (or was switched off) and {exc}",
                fix_hint=(
                    "install the Antigravity CLI so `agy` is on PATH, or put the key in "
                    "~/.claude/scripts/learn_video/.env, then re-run"
                ),
            ) from exc


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="learn-video",
        description="Multimodal knowledge extraction from video platforms.",
    )
    sub = p.add_subparsers(dest="cmd")

    run_p = sub.add_parser("run", help="Execute pipeline on a video URL")
    run_p.add_argument("url")
    run_p.add_argument(
        "--tier",
        choices=("lite", "pro", "max"),
        default=None,
        help="Quality preset (default: lite)",
    )
    run_p.add_argument(
        "--model",
        default=None,
        help="Override vision model, highest precedence (e.g. anthropic:claude-opus-4-7)",
    )
    run_p.add_argument("--offline", action="store_true", help="Route to local Ollama")
    run_p.add_argument(
        "--no-agy",
        action="store_true",
        help="Skip agy even when it is on PATH and use the API stages (needs an API key)",
    )
    run_p.add_argument("--fresh", action="store_true", help="Bypass cache")
    run_p.add_argument(
        "--short",
        action="store_true",
        help="Force whole-video upload (fails if >60s)",
    )
    run_p.add_argument(
        "--notes-only",
        action="store_true",
        help="Skip /learn-eval handoff (produce fused.md and stop)",
    )
    run_p.add_argument(
        "--keep-video",
        action="store_true",
        help="Keep video.mp4 in the cache after fuse (default: pruned, ~99%% of bytes)",
    )

    sub.add_parser("cache-info", help="List cached videos")

    clean_p = sub.add_parser("cache-clean", help="Delete cache dir(s)")
    clean_p.add_argument("video_id", help="Video id to delete, or `all`")

    sub.add_parser("cache-prune", help="Delete media from all cache dirs, keep artifacts")

    return p


def _initial_state(args: argparse.Namespace, loaded: config.LoadedConfig) -> PipelineState:
    # PipelineState is a total=False TypedDict; cast makes mypy happy.
    return cast(PipelineState, {
        "url": args.url,
        "engine": _pick_engine(args),
        "tier": args.tier or loaded.tier_default,
        "offline": bool(args.offline),
        "model_override": args.model,
        "force_short": bool(args.short),
        "fresh": bool(args.fresh),
        "notes_only": bool(args.notes_only) or loaded.notes_only_default,
        "keep_video": bool(args.keep_video) or loaded.keep_video_default,
    })


def _run(args: argparse.Namespace) -> int:
    _maybe_load_dotenv()
    _default_gemini_api_version()
    loaded = config.load()

    from .pipeline import run as run_pipeline  # lazy import: needs langgraph

    try:
        initial = _initial_state(args, loaded)
        _require_api_keys(initial, loaded)
        final = run_pipeline(initial)
    except ConfigurationError as exc:
        logging_.fatal(str(exc), fix_hint=exc.fix_hint)
        return 2
    except EnvironmentError_ as exc:
        logging_.fatal(str(exc), fix_hint=exc.install_cmd)
        return 3
    except TargetError as exc:
        logging_.fatal(str(exc))
        return 4
    except TransientError as exc:
        logging_.fatal(f"transient failure after retries: {exc}")
        return 5
    except LearnVideoError as exc:  # pragma: no cover
        logging_.fatal(str(exc))
        return 6

    out_path = final.get("final_md_path")
    if out_path:
        print(out_path)  # stdout: slash command picks this up
        return 0
    logging_.fatal("pipeline finished without producing fused.md")
    return 1


def _cache_info(_args: argparse.Namespace) -> int:
    entries = cache.list_entries()
    if not entries:
        print("(cache empty)")
        return 0
    width = max(len(e["video_id"]) for e in entries)
    total_bytes = 0
    for e in entries:
        last = _dt.datetime.fromtimestamp(e["last_used"]).strftime("%Y-%m-%d %H:%M")
        size_mb = e["size_bytes"] / (1024 * 1024)
        total_bytes += e["size_bytes"]
        media = "video" if e.get("has_video") else "pruned"
        print(f"  {e['video_id']:<{width}}  {size_mb:8.1f} MB   {last}   {media}")
    print(f"  {'TOTAL':<{width}}  {total_bytes / (1024 * 1024):8.1f} MB")
    return 0


def _cache_prune(_args: argparse.Namespace) -> int:
    touched, freed = cache.prune_all()
    print(f"pruned media from {touched} cache dir(s), freed {freed / (1024 * 1024):.1f} MB")
    return 0


def _cache_clean(args: argparse.Namespace) -> int:
    if args.video_id == "all":
        n = cache.clear_all()
        print(f"removed {n} cache dirs")
        return 0
    removed = cache.clear(args.video_id)
    print("removed" if removed else f"no cache entry for {args.video_id}")
    return 0 if removed else 1


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.cmd == "run" or args.cmd is None and hasattr(args, "url"):
        return _run(args)
    if args.cmd == "cache-info":
        return _cache_info(args)
    if args.cmd == "cache-clean":
        return _cache_clean(args)
    if args.cmd == "cache-prune":
        return _cache_prune(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
