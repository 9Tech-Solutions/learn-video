"""Stage 2: transcript acquisition.

Order of preference:
  1. Platform auto-captions from ingest (seconds, free, no API).
  2. faster-whisper small.en int8 (local CPU, ~30s on 60s clip).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import cache, logging_
from .errors import EnvironmentError_, TransientError

_WHISPER_MODEL = "small.en"
_WHISPER_COMPUTE = "int8"


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_cue_text(text: str) -> str:
    """Strip inline `<timestamp>` / `<c>` tags and collapse whitespace."""
    return _WS_RE.sub(" ", _TAG_RE.sub("", text)).strip()


def _strip_overlap(prev_tail: str, curr: str) -> str:
    """Remove the longest prefix of `curr` that is a suffix of `prev_tail`.

    YouTube's scrolling auto-captions emit each phrase twice, once while
    "typing in" and once in the next cue's persistent display. The overlap
    between consecutive cues is always a clean suffix/prefix boundary, so
    this greedy match cleans the transcript without touching real content.
    """
    if not prev_tail or not curr:
        return curr
    max_k = min(len(prev_tail), len(curr))
    for k in range(max_k, 0, -1):
        # Match suffix-of-prev with prefix-of-curr, only snapping on word edges.
        if prev_tail[-k:] == curr[:k] and (
            k == len(curr) or curr[k:k + 1].isspace() or curr[k - 1:k].isspace()
        ):
            return curr[k:].lstrip()
    return curr


def _parse_vtt(vtt_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Parse a VTT file, returning (joined_text, segment_list).

    Consecutive-cue overlap stripping kills the triplicate text pattern
    that YouTube auto-captions produce; see :func:`_strip_overlap`.
    """
    segments: list[dict[str, Any]] = []
    timecode_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[\.,](\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[\.,](\d{3})"
    )
    current_start: float | None = None
    current_end: float | None = None
    buffer: list[str] = []
    running_tail = ""
    TAIL_KEEP = 400  # chars to look back for overlap

    def flush() -> None:
        nonlocal running_tail
        if current_start is None or not buffer:
            return
        raw_text = _clean_cue_text(" ".join(buffer))
        if not raw_text:
            return
        deduped = _strip_overlap(running_tail, raw_text)
        if not deduped:
            return
        segments.append(
            {"start": current_start, "end": current_end, "text": deduped}
        )
        running_tail = (running_tail + " " + deduped)[-TAIL_KEEP:]

    with vtt_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line or line.startswith(("WEBVTT", "NOTE", "STYLE", "Kind:", "Language:")):
                if not line:
                    flush()
                    current_start = None
                    current_end = None
                    buffer = []
                continue
            m = timecode_re.match(line)
            if m:
                flush()
                buffer = []
                h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
                current_start = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
                current_end = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
                continue
            buffer.append(line)
    flush()
    joined = " ".join(s["text"] for s in segments).strip()
    return joined, segments


def _whisper_transcribe(video_path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise EnvironmentError_(
            "faster-whisper not installed",
            install_cmd="pip install faster-whisper",
        ) from exc

    try:
        model = WhisperModel(_WHISPER_MODEL, device="cpu", compute_type=_WHISPER_COMPUTE)
    except Exception as exc:  # network/disk errors downloading model
        raise TransientError(f"faster-whisper model load failed: {exc}") from exc

    segments_iter, _info = model.transcribe(str(video_path), word_timestamps=True)
    segments: list[dict[str, Any]] = []
    text_chunks: list[str] = []
    for seg in segments_iter:
        words = []
        for w in getattr(seg, "words", None) or []:
            words.append({"start": w.start, "end": w.end, "word": w.word})
        segments.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text.strip(),
                "words": words,
            }
        )
        text_chunks.append(seg.text.strip())
    return " ".join(text_chunks).strip(), segments


def node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)

    # Cache hit: already-computed transcript.json
    if paths.transcript.exists() and not state.get("fresh"):
        try:
            payload = json.loads(paths.transcript.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if payload and payload.get("text"):
            logging_.emit("TRANSCRIBE", "cache hit")
            return {
                "transcript": payload["text"],
                "transcript_source": payload.get("source", "captions"),
            }

    captions_path = state.get("captions_path")
    source: str = "captions"
    text: str = ""
    segments: list[dict[str, Any]] = []

    if captions_path and Path(captions_path).exists():
        with logging_.stage("TRANSCRIBE", "using platform auto-captions"):
            text, segments = _parse_vtt(Path(captions_path))
            source = "captions"

    if not text:
        video_path = state.get("video_path")
        if not video_path or not Path(video_path).exists():
            raise TransientError("no captions and no video file to transcribe")
        with logging_.stage(
            "TRANSCRIBE",
            f"no captions, running faster-whisper {_WHISPER_MODEL} (CPU int8)",
        ):
            text, segments = _whisper_transcribe(Path(video_path))
            source = "whisper"

    paths.transcript.write_text(
        json.dumps({"text": text, "segments": segments, "source": source}, indent=2),
        encoding="utf-8",
    )
    cache.update_meta(paths, transcript_source=source)
    return {"transcript": text, "transcript_source": source}
