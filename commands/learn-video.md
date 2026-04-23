---
description: Extract reusable knowledge from a YouTube/TikTok/Vimeo URL via an audio+visual fused timeline, then handoff to /learn-eval
argument-hint: <url> [--tier=lite|pro|max] [--model=<provider:model>] [--offline] [--fresh] [--short] [--notes-only]
allowed-tools: Bash, Read
---

# /learn-video

Pulls a video from any `yt-dlp`-supported site (1800+ sites, including YouTube, TikTok, Vimeo), transcribes it, identifies visually-important timestamps, extracts keyframes, fuses audio+visual into notes, and hands off to `/learn-eval` to save as a `SKILL.md` under `~/.claude/skills/learned/`.

Six stages: **ingest → transcribe → target → keyframes → vision → fuse**.

## How it routes models

| `--tier` | Targeting | Vision | Notes |
|---|---|---|---|
| `lite` (default) | Gemini 3.1 Flash Lite | Gemini 3.1 Flash Lite | 500 RPD free, ~100 videos/day |
| `pro` | Gemini 3.1 Flash Lite | Gemini 3 Flash | 20 RPD, higher quality |
| `max` | Gemini 3.1 Flash Lite | Claude Opus 4.7 | Uses Claude quota |
| `--offline` | qwen2.5vl:3b (Ollama) | qwen2.5vl:3b | Local, slow |

Override vision model with `--model anthropic:claude-opus-4-7` (highest precedence).

Short videos (< 60s, e.g. TikTok/Shorts) auto-route to a one-shot Gemini File API upload on `lite`/`pro` tiers. `--short` forces this path and fails fast on videos >60s. `--offline` and `--max` fall back to keyframe stitching even for short videos (those providers can't ingest raw video).

## Instructions

1. **Parse arguments.** The URL is required. Collect any flags (`--tier`, `--model`, `--offline`, `--fresh`, `--short`, `--notes-only`).

2. **Run the pipeline** by invoking the CLI:

   ```bash
   python -m learn_video.cli run "$URL" [FLAGS...]
   ```

   Run it from `~/.claude/scripts/` so `learn_video` imports cleanly. Stdout is the path to `fused.md`; stderr carries `[N/6 STAGE]` progress lines.

3. **Read the resulting `fused.md`** with the Read tool. Show the user a concise summary (title, timeline length, sample `FUSED:` lines).

4. **Handoff to /learn-eval** unless `--notes-only`. Pass the `fused.md` contents for verdict + optional save-as-skill.

5. **Report artifacts**: cache dir (`~/.claude/cache/learn-video/<video-id>/`), final md path, models used.

## Error handling

- `[FATAL] GEMINI_API_KEY required` → tell the user to export it, or to put it in `~/.claude/scripts/learn_video/.env`.
- `[FATAL] --short requires video < 60s` → drop the flag or pick a shorter clip.
- `[FATAL] yt-dlp not found on PATH` → instruct `pip install yt-dlp`.
- `[FATAL] ffmpeg not found` → `choco install ffmpeg` (or apt/brew).
- `[FATAL] transient failure after retries` → usually a 429; suggest retry later or `--tier=max` to switch off Gemini free tier.

## Cache management

- `python -m learn_video.cli cache-info`: list videos, sizes, last-used.
- `python -m learn_video.cli cache-clean <video-id>`: remove one.
- `python -m learn_video.cli cache-clean all`: nuke everything.

Cache dir: `~/.claude/cache/learn-video/<video-id>/` contains `meta.json`, `video.*`, `captions.vtt`, `transcript.json`, `targets.json`, `frames/*.jpg`, `fused.md`.

## First-time setup

```bash
pip install -r ~/.claude/scripts/learn_video/requirements.txt
export GEMINI_API_KEY=...     # or put in ~/.claude/scripts/learn_video/.env
# anthropic key only needed for --tier=max or --model anthropic:*
```
