---
description: Extract reusable knowledge from a YouTube/TikTok/Vimeo URL via an audio+visual fused timeline (agy watches the video when installed, otherwise the API tiers run), then handoff to /learn-eval
argument-hint: <url> [--no-agy] [--tier=lite|pro|max] [--model=<provider:model>] [--offline] [--fresh] [--short] [--notes-only] [--keep-video]
allowed-tools: Bash, Read, AskUserQuestion
---

# /learn-video

Pulls a video from any `yt-dlp`-supported site (1800+ sites, including YouTube, TikTok, Vimeo), transcribes it, fuses what is said with what is on screen into a timeline of notes, and hands off to `/learn-eval` to save as a `SKILL.md` under `~/.claude/skills/learned/`.

A `prune` step deletes the downloaded media (video + raw captions) once `fused.md` exists. Every other artifact stays, so a re-run of the same URL costs zero downloads and zero model calls.

## How it routes

The CLI checks for agy first.

| Order | Condition | Route | Needs |
|---|---|---|---|
| 1 | `agy` (the Antigravity CLI) is on PATH and no `--tier`, `--model`, `--offline` or `--no-agy` was passed | **agy**: ingest → transcribe → agy watches the whole video (picture and sound) in one sandboxed, read-only call → fuse | no API key, agy's own quota |
| 2 | agy is missing, switched off (`LEARN_VIDEO_AGY=off`), or a provider flag was passed | **API stages**: ingest → transcribe → target → keyframes → vision → classify → fuse | `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY` for `--tier=max`) |

The agy model defaults to `gemini-4-argon-high`. Override it with `LEARN_VIDEO_AGY_MODEL` or `[agy] model` in `config.toml`. Videos over 60 MB get a 360p proxy before agy sees them.

API tiers:

| `--tier` | Targeting | Vision | Notes |
|---|---|---|---|
| `lite` | Gemini Flash Lite (`-latest`) | Gemini Flash Lite (`-latest`) | 500 RPD free, ~100 videos/day |
| `pro` | Gemini Flash Lite (`-latest`) | Gemini Flash (`-latest`) | 20 RPD, higher quality |
| `max` | Gemini Flash Lite (`-latest`) | Claude Opus 4.7 | Uses Claude quota |
| `--offline` | qwen2.5vl:3b (Ollama) | qwen2.5vl:3b | Local, slow |

On the API route, `--model anthropic:claude-opus-4-7` overrides the vision model (highest precedence), and short videos (< 60s, e.g. TikTok/Shorts) go to a one-shot Gemini File API upload on `lite`/`pro`. `--short` forces that path and fails fast on videos > 60s.

## Instructions

1. **Parse arguments.** The URL is required. Collect any flags.

2. **Run the pipeline** by invoking the CLI:

   ```bash
   python -m learn_video.cli run "$URL" [FLAGS...]
   ```

   Run it from wherever `learn_video` is importable. Stdout is the path to `fused.md`. Stderr carries progress lines, and the first `[info] running pipeline engine=...` line says which route ran. An agy run takes a few minutes, so run it in the background and wait for it to exit.

3. **No agy and no API key.** When the run exits 2 with `[FATAL] NO_AGY_NO_API_KEY`, nothing was downloaded. Ask the user (AskUserQuestion): install the Antigravity CLI so `agy` is on PATH, or add a Gemini API key. Tell them to write the key into the `.env` file (`GEMINI_API_KEY=...`) themselves in an editor. Never ask them to paste a key into the chat, and never read or print the `.env` file. Re-run once they confirm.

4. **Read the resulting `fused.md`** with the Read tool. Show the user a concise summary (title, route and model, timeline length, sample `FUSED:` lines).

5. **Handoff to /learn-eval** unless `--notes-only`. Pass the `fused.md` contents for verdict + optional save-as-skill.

6. **Report artifacts**: cache dir (`~/.claude/cache/learn-video/<video-id>/`), final md path, route and models used.

## Error handling

- `[FATAL] NO_AGY_NO_API_KEY` → step 3 above.
- `agy exited N` or `agy returned no notes (quota exhausted mid-run?)` → agy's quota is out or the run broke. Retry later, or re-run with `--no-agy` if the user has an API key.
- `agy could not open the video file` → re-run with `--no-agy`.
- `[FATAL] --short requires video < 60s` → drop the flag or pick a shorter clip.
- `[FATAL] yt-dlp not found on PATH` → instruct `pip install yt-dlp`.
- `[FATAL] ffmpeg not found` → `choco install ffmpeg` (or apt/brew).
- `[FATAL] transient failure after retries` → usually a 429. Suggest a retry later, or `--tier=max` to move off the Gemini free tier.
- `... media was pruned, re-run with --fresh` → the cached run never reached that stage and the video is gone. Add `--fresh`.

## Cache management

- `python -m learn_video.cli cache-info`: list videos, sizes, last-used, whether media is still present.
- `python -m learn_video.cli cache-prune`: delete media from every entry, keep notes and transcripts.
- `python -m learn_video.cli cache-clean <video-id>`: remove one.
- `python -m learn_video.cli cache-clean all`: remove everything.

Cache dir: `~/.claude/cache/learn-video/<video-id>/` keeps `meta.json` (includes cached notes blocks from either route), `transcript.json`, `targets.json`, `frames/*.jpg`, `fused.md`. `video.*` and `video*.vtt` exist only during a run unless `--keep-video` (or `keep_video = true` in `config.toml`). Caption download failures (YouTube answers HTTP 429 under rate limits) only log a warning, and whisper transcribes instead.

## First-time setup

```bash
pip install -r requirements.txt
# agy route: install the Antigravity CLI so `agy` is on PATH. No key needed.
# API route only: export GEMINI_API_KEY=...  (or put it in .env)
# anthropic key only needed for --tier=max or --model anthropic:*
```
