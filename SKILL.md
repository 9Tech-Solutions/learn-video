---
name: learn-video
description: Extract reusable knowledge from a YouTube/TikTok/Vimeo URL via a 6-stage audio+visual fused timeline (ingest → transcribe → probe → target/summary → vision → classify → fuse). Hands off to /learn-eval so the output lands in the right bin (skill, rule, tip, note, discard). Use this when the user shares a video URL and wants extracted notes, not when they want the video downloaded or clipped.
license: MIT. See LICENSE.
---

# learn-video

Pull a video from any `yt-dlp`-supported site (1800+ including YouTube, TikTok, Vimeo), align its audio with what's on screen, and produce a `fused.md` timeline ready for `/learn-eval` to save as a `SKILL.md`, rule, tip, or note.

Unlike transcript-only skills, this one uses an LLM to pick which timestamps need a visual reference, extracts just those frames with ffmpeg, and asks a vision model to fuse each frame with its transcript window. The output reads as `AUDIO / VISUAL / FUSED` blocks aligned to `[mm:ss]` markers.

## When to use

- User shares a tutorial, talk, or short-form dev clip and wants the knowledge, not the video.
- User wants a consistent pipeline from many videos (e.g. an entire creator's channel) into the ECC knowledge system.
- Output needs to flow into `/learn-eval`: the `recommended-form:` header in `fused.md` is designed for that handoff.

## When *not* to use

- User wants the video file itself, subtitles, or clipped highlights; use `yt-dlp` or a clipping tool directly.
- Only the raw transcript is needed; a lightweight transcript skill is faster (no vision calls, no rate limiting).
- Live streams or content gated behind authentication.

## Quick start

```bash
# one-time setup (from this repo)
./setup.sh

# run it
python -m learn_video.cli run "https://www.youtube.com/watch?v=<id>"

# flags
python -m learn_video.cli run "<url>" \
  --tier=lite|pro|max        # model quality preset
  --model=<provider:model>   # override vision model (highest precedence)
  --offline                  # route to local Ollama
  --fresh                    # bypass cache
  --short                    # force whole-video File API upload (fails if >60s)
  --notes-only               # skip /learn-eval handoff
```

Stdout is the path to `fused.md`. Stderr carries `[N/6 STAGE]` progress lines. Claude should read `fused.md` after the CLI returns and hand off to `/learn-eval` unless `--notes-only`.

## Invocation from the slash command

The slash command `~/.claude/commands/learn-video.md` drives Claude to:

1. Parse the URL and flags.
2. Shell out to `python -m learn_video.cli run "$URL" [flags]` from the repo root (or wherever `learn_video` is importable).
3. Read the resulting `fused.md`.
4. Summarize the timeline for the user (title, `video-kind`, `recommended-form`, block count, 1–2 highlight `FUSED:` lines).
5. Unless `--notes-only`, invoke `/learn-eval` with the `fused.md` contents.

## Pipeline stages (in `learn_video/`)

| Stage | Module | Purpose |
|---|---|---|
| 1. Ingest | `ingest.py` | `yt-dlp` metadata probe + download; picks 720p/480p/360p by duration |
| 2. Transcribe | `transcribe.py` | Platform auto-captions first, `faster-whisper small.en` fallback |
| Probe | `probe.py` | Classifies video as `visual | audio | mixed` from 5 sample frames |
| 3a. Target | `target.py` | LLM picks 3–15 timestamps worth a frame (sliding 15-min windows for >25-min videos) |
| 3b. Summary | `summary.py` | Audio-first path: chapter-style transcript summary, no frames |
| 4. Keyframes | `keyframes.py` | `ffmpeg` extracts one JPEG per target timestamp |
| 5. Vision | `vision.py` | Per-frame fusion, 6-way concurrent; plus whole-video File API path for <60s clips |
| Classify | `classify.py` | Suggests `recommended-form`: `skill | rule | tip | note | discard` |
| 6. Fuse | `fuse.py` | Composes `fused.md` with headers + timeline |

## Model portability

Only `model_client.py` imports `langchain-*`. Every stage calls:

- `build_chat_model(model_id, **kwargs)`: `<provider>:<model>` id strings (e.g. `google_genai:gemini-flash-lite-latest`, `anthropic:claude-opus-4-7`, `ollama:qwen2.5vl:3b`).
- `invoke_structured(model, schema, messages)`: Pydantic schema validation with a `json_repair` fallback and an empty-response short-circuit.
- `invoke_vision(model, vision_input)`: portable `image_url` + data-URL shape that works on Gemini, Claude, and Ollama; `video_path` is Gemini-only (File API upload).

A sliding-window rate limiter (13 req / 60s on Flash Lite) gates every provider call. To swap models, edit `TIER_MODELS` in `config.py`. Stage code does not change.

## Tier → model mapping

| `--tier` | Targeting | Vision | Quota notes |
|---|---|---|---|
| `lite` (default) | `gemini-flash-lite-latest` | `gemini-flash-lite-latest` | ~100 videos/day on free 500 RPD |
| `pro` | `gemini-flash-lite-latest` | `gemini-flash-latest` | 20 RPD cap on Flash |
| `max` | `gemini-flash-lite-latest` | `claude-opus-4-7` | Uses Claude quota |
| `--offline` | `qwen2.5vl:3b` | `qwen2.5vl:3b` | Local Ollama, slow |

Targeting always stays on Flash Lite; it's a cheap text task, and keeping the premium budget for vision is almost always correct.

## Cache

`~/.claude/cache/learn-video/<video-id>/` contains `meta.json`, `video.*`, `captions.vtt`, `transcript.json`, `targets.json`, `frames/*.jpg`, `fused.md`. Every stage checks its artifact before running; re-runs on the same URL skip straight to whatever changed.

```bash
python -m learn_video.cli cache-info             # list cached videos
python -m learn_video.cli cache-clean <video-id> # remove one
python -m learn_video.cli cache-clean all        # nuke everything
```

## Error taxonomy

| Class | Behavior | Example |
|---|---|---|
| `TransientError` | Auto-retries (tenacity: 5s, 10s, 20s with jitter; max 3) | 429, `httpx.ReadError`, timeout |
| `ConfigurationError` | Fail fast with fix hint | missing `GEMINI_API_KEY` |
| `EnvironmentError_` | Fail fast with install command | `ffmpeg not found` |
| `TargetError` | Unrecoverable | DRM-blocked, deleted video |

## Requirements

- Python 3.13 (tested; 3.11+ should work, `tomllib` fallback to `tomli` already in place)
- `ffmpeg` on PATH
- `yt-dlp` on PATH (installed via `pip install -r requirements.txt`)
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) for the default `lite` / `pro` tiers
- `ANTHROPIC_API_KEY` if using `--tier=max` or `--model anthropic:*`
- Local Ollama with `qwen2.5vl:3b` pulled if using `--offline`

See `README.md` for a full architecture diagram and the 12-video demo output.
