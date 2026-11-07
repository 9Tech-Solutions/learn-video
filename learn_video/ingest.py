"""Stage 1: yt-dlp downloads video + auto-captions, detects duration.

Idempotent: re-runs short-circuit against the cache. Sets ``is_short_video``
so the probe_short router in ``pipeline.py`` can branch.
"""

from __future__ import annotations

import contextlib
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

    The video only feeds ffmpeg frame grabs (JPEG q4) and, for <60s clips,
    one Gemini upload. 480p is readable for code-on-screen content and is
    roughly half the bytes of 720p, so it is the ceiling for everything up
    to 90 min. Past that, 360p: the probe classifies most of those as
    audio-first anyway. Raise the cap here if a run produces unreadable
    frames.
    """
    if duration_s > 90 * 60:       # >1.5h → 360p
        return "bv*[height<=360]+ba/b[height<=360]/worst"
    return "bv*[height<=480]+ba/b[height<=480]/best"


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
            # Captions are best effort. YouTube answers the caption endpoint
            # with HTTP 429 under rate limits, and yt-dlp's default
            # ignoreerrors='only_download' turns that into a fatal error with
            # no video. -i downgrades it to a warning, a failed video download
            # still exits 1, and transcribe falls back to whisper.
            "--ignore-errors",
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
    found = cache.find_video(cache.CachePaths(root=out_dir))
    if found is None:
        raise TransientError("yt-dlp completed but no output file found")
    return found


def _find_caption(out_dir: Path) -> Path | None:
    """Pick one caption track and drop the duplicates.

    `--sub-langs en.*` pulls both `en` and `en-orig` for English videos, and
    they are byte-identical for auto-captions. Keep the first sorted track and
    delete the rest so a 2.5h talk does not store 1.4 MB twice.
    """
    candidates = sorted(out_dir.glob("video*.vtt"))
    if not candidates:
        return None
    keep, *extras = candidates
    for extra in extras:
        with contextlib.suppress(OSError):
            extra.unlink()
    return keep


def node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node: returns the state keys it updates."""
    url = state["url"]
    video_id = state.get("video_id") or cache.derive_video_id(url)
    # Do not create the dir yet: for non-YouTube URLs the derived id is a
    # URL hash that yt-dlp replaces with the canonical id below, and an
    # early mkdir leaves an empty orphan folder per run.
    paths = cache.paths_for(video_id)

    with logging_.stage("INGEST", f"probing metadata for {url}"):
        # Cache check: meta + (video OR derived artifacts) means no network.
        # After `prune` the video is gone but transcript/frames/fused remain,
        # and every downstream stage can run from those.
        existing_meta = cache.read_meta(paths)
        video_file = cache.find_video(paths)
        resumable = video_file is not None or cache.has_artifacts(paths)
        if existing_meta.get("duration_s") is not None and resumable and not state.get("fresh"):
            logging_.info(
                f"cache hit, video_id={video_id}"
                + ("" if video_file else " (media pruned, running from artifacts)")
            )
            duration = float(existing_meta["duration_s"])
            title = existing_meta.get("title")
            captions_path = existing_meta.get("captions_path")
            if captions_path and not Path(captions_path).exists():
                captions_path = None
            return _ingest_return(
                video_id, paths, title, duration,
                str(video_file) if video_file else None, captions_path,
            )

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
    if captions_path is None:
        logging_.warn("no platform captions (missing or rate limited), whisper will transcribe")

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
