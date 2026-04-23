"""Stage 1 — yt-dlp: download video + auto-captions, detect duration.

Idempotent: re-runs short-circuit against the cache. Sets ``is_short_video``
so the probe_short router in ``pipeline.py`` can branch.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import cache, logging_
from .errors import EnvironmentError_, TargetError, TransientError

SHORT_VIDEO_THRESHOLD_S = 60.0


def _require_ytdlp() -> str:
    path = shutil.which("yt-dlp")
    if not path:
        raise EnvironmentError_(
            "yt-dlp not found on PATH",
            install_cmd="pip install yt-dlp",
        )
    return path


def _probe_metadata(url: str) -> dict[str, Any]:
    """Run `yt-dlp --dump-json` without downloading the video bytes."""
    ytdlp = _require_ytdlp()
    try:
        proc = subprocess.run(
            [ytdlp, "--dump-json", "--no-warnings", "--skip-download", url],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise TransientError(f"yt-dlp metadata probe timed out for {url}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").lower()
        if any(
            k in stderr for k in ("private", "deleted", "unavailable", "removed", "drm")
        ):
            raise TargetError(f"Video is inaccessible: {exc.stderr.strip()}") from exc
        raise TransientError(f"yt-dlp probe failed: {exc.stderr.strip()}") from exc
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise TransientError("yt-dlp returned unparseable JSON") from exc


def _format_for_duration(duration_s: float) -> str:
    """Pick a yt-dlp format string scaled to video length.

    Long videos at 720p blow past download timeouts (a 2.5h talk is ~3GB).
    Frame quality matters for the vision stage, but 480p is readable for
    most code-on-screen content, and 360p is fine for anything that would
    be classified as audio-first anyway.
    """
    if duration_s > 90 * 60:       # >1.5h → 360p
        return "bv*[height<=360]+ba/b[height<=360]/worst"
    if duration_s > 30 * 60:       # 30–90min → 480p
        return "bv*[height<=480]+ba/b[height<=480]/best"
    return "bv*[height<=720]+ba/b[height<=720]/best"


def _timeout_for_duration(duration_s: float) -> int:
    """Scale download timeout with video length; clamp to 1h."""
    return min(3600, max(900, int(duration_s * 0.5) + 600))


def _download_video(url: str, out_dir: Path, duration_s: float = 0.0) -> Path:
    ytdlp = _require_ytdlp()
    tmpl = str(out_dir / "video.%(ext)s")
    fmt = _format_for_duration(duration_s)
    proc = subprocess.run(
        [
            ytdlp,
            "-f", fmt,
            "--merge-output-format", "mp4",
            "--write-auto-subs",
            "--sub-langs", "en.*",
            "--sub-format", "vtt",
            "-o", tmpl,
            "--no-warnings",
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=_timeout_for_duration(duration_s),
    )
    if proc.returncode != 0:
        raise TransientError(f"yt-dlp download failed: {proc.stderr.strip()}")
    # yt-dlp may land on .mp4 / .webm / .mkv depending on sources
    for ext in ("mp4", "webm", "mkv", "m4a"):
        candidate = out_dir / f"video.{ext}"
        if candidate.exists():
            return candidate
    raise TransientError("yt-dlp completed but no output file found")


def _find_caption(out_dir: Path) -> Path | None:
    for candidate in sorted(out_dir.glob("video*.vtt")):
        return candidate
    return None


def node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node — returns the state keys it updates."""
    url = state["url"]
    video_id = state.get("video_id") or cache.derive_video_id(url)
    paths = cache.ensure_dir(video_id)

    with logging_.stage("INGEST", f"probing metadata for {url}"):
        # Cache check: if we already have video + meta, skip the network.
        existing_meta = cache.read_meta(paths)
        have_video = paths.video.exists() or any(paths.root.glob("video.*"))
        if existing_meta.get("duration_s") is not None and have_video and not state.get("fresh"):
            logging_.info(f"cache hit — video_id={video_id}")
            duration = float(existing_meta["duration_s"])
            title = existing_meta.get("title")
            video_path = existing_meta.get("video_path") or str(next(iter(paths.root.glob("video.*"))))
            captions_path = existing_meta.get("captions_path")
            return _ingest_return(video_id, paths, title, duration, video_path, captions_path)

        meta = _probe_metadata(url)

    title = meta.get("title")
    # Prefer explicit id from yt-dlp; it's more reliable than URL parsing.
    video_id = meta.get("id") or video_id
    paths = cache.ensure_dir(video_id)
    duration = float(meta.get("duration") or 0.0)

    with logging_.stage(
        "INGEST",
        f"downloading {title or url!r} ({duration / 60:.1f} min)",
    ):
        video_path = _download_video(url, paths.root, duration_s=duration)
    captions_path = _find_caption(paths.root)

    cache.update_meta(
        paths,
        video_id=video_id,
        url=url,
        title=title,
        duration_s=duration,
        video_path=str(video_path),
        captions_path=str(captions_path) if captions_path else None,
    )
    return _ingest_return(
        video_id,
        paths,
        title,
        duration,
        str(video_path),
        str(captions_path) if captions_path else None,
    )


def _ingest_return(
    video_id: str,
    paths: cache.CachePaths,
    title: str | None,
    duration: float,
    video_path: str | None,
    captions_path: str | None,
) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "cache_dir": str(paths.root),
        "title": title,
        "duration_s": duration,
        "is_short_video": 0 < duration <= SHORT_VIDEO_THRESHOLD_S,
        "video_path": video_path,
        "captions_path": captions_path,
    }
