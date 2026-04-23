"""CLI entry point: `python -m learn_video.cli <subcommand> [args]`.

Subcommands:
  run <url>        — execute the 6-stage pipeline (default)
  cache-info       — list cached video-ids, sizes, last-used
  cache-clean ID   — delete one cache dir (or `all`)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import Any

from . import cache, config, logging_
from .errors import (
    ConfigurationError,
    EnvironmentError_,
    LearnVideoError,
    TargetError,
    TransientError,
)


def _maybe_load_dotenv() -> None:
    """Load `~/.claude/scripts/learn_video/.env` if python-dotenv is installed."""
    env_path = Path.home() / ".claude" / "scripts" / "learn_video" / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        return
    load_dotenv(env_path, override=False)


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

    sub.add_parser("cache-info", help="List cached videos")

    clean_p = sub.add_parser("cache-clean", help="Delete cache dir(s)")
    clean_p.add_argument("video_id", help="Video id to delete, or `all`")

    return p


def _run(args: argparse.Namespace) -> int:
    _maybe_load_dotenv()
    loaded = config.load()
    tier = args.tier or loaded.tier_default

    from .pipeline import run as run_pipeline  # lazy import: needs langgraph

    initial: dict[str, Any] = {
        "url": args.url,
        "tier": tier,
        "offline": bool(args.offline),
        "model_override": args.model,
        "force_short": bool(args.short),
        "fresh": bool(args.fresh),
        "notes_only": bool(args.notes_only) or loaded.notes_only_default,
    }

    try:
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
        print(out_path)  # stdout — slash command picks this up
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
        print(f"  {e['video_id']:<{width}}  {size_mb:8.1f} MB   {last}")
    print(f"  {'TOTAL':<{width}}  {total_bytes / (1024 * 1024):8.1f} MB")
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
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
