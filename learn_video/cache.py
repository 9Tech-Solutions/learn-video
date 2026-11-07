"""Artifact-based cache under ``~/.claude/cache/learn-video/<video-id>/``.

Each stage checks for its output before running, which also gives us free
retry idempotency (see plan §9). LangGraph's SQLite checkpointer is *not*
used as primary cache; artifacts ARE the checkpoints.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CACHE_ROOT = Path.home() / ".claude" / "cache" / "learn-video"

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


def derive_video_id(url: str) -> str:
    """Stable per-URL directory name.

    YouTube-style 11-char IDs are preserved when present; otherwise we fall
    back to a URL hash prefix so unusual inputs still get a stable folder.
    """
    # yt-dlp will give us the canonical id later; for cache-dir resolution
    # we use either the embedded id or a deterministic prefix so
    # *probing the cache before ingest* still works on repeat runs.
    m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_\-]{11})", url)
    if m:
        return m.group(1)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    safe = _SAFE.sub("_", url)[-32:]
    return f"{digest}_{safe}"


@dataclass(frozen=True)
class CachePaths:
    root: Path

    @property
    def meta(self) -> Path:
        return self.root / "meta.json"

    @property
    def video(self) -> Path:
        return self.root / "video.mp4"

    @property
    def captions(self) -> Path:
        return self.root / "captions.vtt"

    @property
    def transcript(self) -> Path:
        return self.root / "transcript.json"

    @property
    def targets(self) -> Path:
        return self.root / "targets.json"

    @property
    def frames_dir(self) -> Path:
        return self.root / "frames"

    def frame(self, t: float) -> Path:
        # Fixed width so `ls` sorts chronologically
        return self.frames_dir / f"{t:09.2f}.jpg"

    @property
    def fused(self) -> Path:
        return self.root / "fused.md"


MEDIA_EXTS: tuple[str, ...] = ("mp4", "webm", "mkv", "m4a")


def paths_for(video_id: str) -> CachePaths:
    return CachePaths(root=CACHE_ROOT / video_id)


def find_video(paths: CachePaths) -> Path | None:
    """Return the downloaded media file if any survives in the cache dir."""
    for ext in MEDIA_EXTS:
        candidate = paths.root / f"video.{ext}"
        if candidate.exists():
            return candidate
    return None


def has_artifacts(paths: CachePaths) -> bool:
    """True when the expensive stages already left reusable output behind."""
    return paths.transcript.exists() or paths.fused.exists()


def prune_media(paths: CachePaths) -> int:
    """Delete the bulky inputs (video + raw captions) once derived artifacts exist.

    Keeps meta.json, transcript.json, targets.json, frames/ and fused.md, which
    together are ~1% of the download and are all a re-run needs. Returns bytes
    freed. The caption files are only removed once transcript.json exists, so
    a run that died before transcription can still resume from captions.
    """
    freed = 0
    victims: list[Path] = [p for p in (find_video(paths),) if p is not None]
    if paths.transcript.exists():
        victims.extend(paths.root.glob("video*.vtt"))
    for victim in victims:
        try:
            size = victim.stat().st_size
            victim.unlink()
            freed += size
        except OSError:
            continue
    return freed


def ensure_dir(video_id: str) -> CachePaths:
    p = paths_for(video_id)
    p.root.mkdir(parents=True, exist_ok=True)
    p.frames_dir.mkdir(parents=True, exist_ok=True)
    return p


def clear(video_id: str) -> bool:
    """Delete a single video's cache dir. Returns True if something was removed."""
    p = paths_for(video_id)
    if p.root.exists():
        shutil.rmtree(p.root)
        return True
    return False


def clear_all() -> int:
    """Delete the whole cache root. Returns the count of removed dirs."""
    if not CACHE_ROOT.exists():
        return 0
    count = sum(1 for entry in CACHE_ROOT.iterdir() if entry.is_dir())
    shutil.rmtree(CACHE_ROOT)
    return count


def list_entries() -> list[dict[str, Any]]:
    """Return one record per cached video-id: size, last-used, artifact list."""
    if not CACHE_ROOT.exists():
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(CACHE_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        total = 0
        latest_mtime = 0.0
        for dirpath, _, files in os.walk(entry):
            for f in files:
                fp = os.path.join(dirpath, f)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                total += st.st_size
                if st.st_mtime > latest_mtime:
                    latest_mtime = st.st_mtime
        out.append(
            {
                "video_id": entry.name,
                "size_bytes": total,
                "last_used": latest_mtime,
                "path": str(entry),
                "has_video": find_video(CachePaths(root=entry)) is not None,
            }
        )
    return out


def prune_all() -> tuple[int, int]:
    """Strip media from every cached entry. Returns (entries_touched, bytes_freed)."""
    if not CACHE_ROOT.exists():
        return 0, 0
    touched = 0
    freed = 0
    for entry in sorted(CACHE_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        got = prune_media(CachePaths(root=entry))
        if got:
            touched += 1
            freed += got
    return touched, freed


def write_meta(paths: CachePaths, meta: dict[str, Any]) -> None:
    paths.meta.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")


def read_meta(paths: CachePaths) -> dict[str, Any]:
    if not paths.meta.exists():
        return {}
    try:
        return json.loads(paths.meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_meta(paths: CachePaths, **updates: Any) -> dict[str, Any]:
    merged = read_meta(paths)
    merged.update(updates)
    write_meta(paths, merged)
    return merged
