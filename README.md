# learn-video

[![tests](https://github.com/9Tech-Solutions/learn-video/actions/workflows/tests.yml/badge.svg)](https://github.com/9Tech-Solutions/learn-video/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![skills.sh](https://img.shields.io/badge/skills.sh-9Tech--Solutions%2Flearn--video-black)](https://skills.sh/9Tech-Solutions/learn-video/learn-video)

> Read a video the way a careful viewer would — narration paired with what's on screen at the moment an idea is taught.

## Why this exists

A transcript tells you what someone said. But creators don't film themselves for fun — every time a person picks video over an article, they're choosing to show you something words alone can't carry. The diagram they point at. The line of code they highlight. The UI they click through. The terminal output they leave hanging on screen while they explain it. When a tool reduces a video to its transcript, it keeps the words and throws away **the reason the video existed in the first place**.

This matters more than it sounds. A tutorial narrator says _"just add this and that here"_ while their cursor hovers over `--experimental-modules`. A system-design talk says _"and the cache looks like this"_ while a diagram shows three very specific layers. A short-form clip says _"avoid this pattern"_ while the screen shows the exact 4-line anti-pattern. The transcript saves the narration. The video saves the answer. A transcript-only tool leaves you with half the lesson.

`learn-video` reads both. An LLM scans the transcript and picks the handful of moments where **the screen actually matters** — typically 3 to 15 for a 20-minute video. `ffmpeg` pulls just those frames. A vision model pairs each frame with the narration around it. The output is a timeline of self-contained notes — one per teaching moment — that read like what a careful viewer would have written down. Not a wall of text. Not a summary. Notes.

## Who it's for

- **Developers** harvesting knowledge from tutorials, talks, TikTok clips, and conference recordings into a skill library (`/learn-eval` routes the output into skills, rules, tips, or notes automatically).
- **Learners** who want a searchable reference of "what was shown at 14:23 when they said _this part is important_."
- **Content curators** pulling the one reusable idea from a long video without re-watching it.
- **Anyone** who has ever paused a tutorial, screenshotted the screen, and typed the caption into a note app by hand.

## What the output looks like

A 1m 7s TikTok on clean-code principles (`@s4.codes/video/7617132278875016470`) produces:

```markdown
# The simplest formatting rules do the most heavy lifting.

- **recommended-form:** `rule` — The video establishes a consistent convention
  for using vertical whitespace to improve code readability and structure.
- **video-kind:** `visual` (confidence 1.00) — The video consists entirely of
  code snippets and text overlays...
- **URL:** https://www.tiktok.com/@s4.codes/video/7617132278875016470
- **Targeting model:** `google_genai:gemini-flash-lite-latest`
- **Vision model:** `google_genai:gemini-flash-lite-latest`

## Timeline

### [00:12]

**AUDIO:** Grouping import statements and separating them from function
definitions with a blank line...

**VISUAL:** A code editor showing Python imports grouped at the top,
separated by one blank line from the first function definition.

**FUSED:** Vertical whitespace is a zero-cost readability signal: a single
blank line between logical groups (imports vs. code, function vs. function)
tells the reader "new section" faster than any formatting rule could.
```

A 2h 39min conference talk (`W4EwfEU8CGA`, _Let's Handle 1M Requests/sec_) produces 25 blocks via a 10-window sliding targeting pass. A 1-minute YouTube Short goes through the whole-video File API upload path and produces a single compact fused block.

## Quickstart

**If you just want it as a Claude Code skill** (or Codex, Cursor, Windsurf — any agent that reads SKILL.md):

```bash
npx skills add 9Tech-Solutions/learn-video
```

The `skills` CLI clones the repo and symlinks the skill into every agent install it finds on your machine. You still need `ffmpeg`, `yt-dlp`, and a `GEMINI_API_KEY` before the pipeline can actually run — see below.

**If you want to run the CLI directly, modify the code, or use it without Claude Code:** follow the four steps below.

### 1. Clone and install

```bash
git clone https://github.com/9Tech-Solutions/learn-video
cd learn-video
./setup.sh
```

The setup script creates a virtualenv, installs pinned requirements (`langgraph`, `langchain-*`, `yt-dlp`, `faster-whisper`, `pydantic`, `tenacity`, `json-repair`), and prints the next steps. Requires Python 3.13 (3.11+ should work) and `ffmpeg` on PATH.

### 2. Provide API keys

```bash
cp .env.example .env
# edit .env: GEMINI_API_KEY=...  (required)
#           ANTHROPIC_API_KEY=... (only for --tier=max)
```

Or export them directly:

```bash
export GEMINI_API_KEY=...
```

### 3. Run

```bash
python -m learn_video.cli run "https://www.youtube.com/watch?v=<id>"
```

You'll see `[N/6 STAGE]` lines on stderr and the final `fused.md` path on stdout. Everything is cached under `~/.claude/cache/learn-video/<video-id>/` so reruns are free.

### 4. Install as a Claude Code skill (optional)

Copy the slash command and the package into your Claude config:

```bash
mkdir -p ~/.claude/commands ~/.claude/scripts
cp commands/learn-video.md ~/.claude/commands/
cp -r learn_video ~/.claude/scripts/
```

After that, `/learn-video <url>` inside Claude Code drives the pipeline and hands off to `/learn-eval`.

## How it compares to other video skills

A survey of [skills.sh](https://skills.sh/) and five adjacent registries (April 2026) returned ~10 YouTube-related skills and zero that do audio-visual fused knowledge extraction. Most are transcript fetchers. One (`youtube-clipper`) downloads and cuts video but never reads the frames. `learn-video` is the only one that pairs narration with on-screen content.

| Capability | Transcript skills | YouTube-clipper | **learn-video** |
|---|:---:|:---:|:---:|
| YouTube transcript | ✅ | ✅ | ✅ |
| Multi-platform (TikTok, Vimeo, 1800+ sites) | ❌ | ❌ | ✅ |
| Whisper fallback when captions are missing | ❌ | ❌ | ✅ |
| Cleans up YouTube's duplicated scroll-captions | ❌ | ❌ | ✅ |
| LLM picks which moments need a frame | ❌ | ❌ | ✅ |
| Vision model actually reads the frame | ❌ | ❌ | ✅ |
| Output pairs narration with what's on screen | ❌ | ❌ | ✅ |
| Detects podcasts / talking-head (skips vision cost) | ❌ | ❌ | ✅ |
| Short-video fast path (whole-video upload) | ❌ | ❌ | ✅ |
| Handles 1–3 hour videos via sliding windows | ❌ | ❌ | ✅ |
| Swap models without code changes (Gemini / Claude / local) | ❌ | ❌ | ✅ |
| Classifies output for knowledge-system routing | ❌ | ❌ | ✅ |

## How it works

Six stages, in plain language:

1. **Ingest** — download the video and its captions if any (uses `yt-dlp`, which supports 1800+ sites).
2. **Transcribe** — if the platform doesn't have captions, run a local whisper model on the audio.
3. **Probe** — sample 5 frames across the video and ask the LLM: _is this a tutorial with stuff on screen, or is it a podcast / talking head where the visuals don't really matter?_ If it's the latter, skip the expensive visual path and just summarize the transcript into chapters.
4. **Target** — read the transcript, pick the handful of timestamps where what's on screen actually carries the idea. For videos over 25 minutes, split the transcript into 15-minute windows and pick per window so long talks don't get shortchanged.
5. **Vision** — pull a frame at each target with `ffmpeg`, ask a vision model what's on screen, and fuse it with the surrounding narration. Up to 6 frames are processed in parallel.
6. **Fuse** — compose the final markdown. Before that, one more quick LLM call decides whether the result is a reusable skill, a rule, a tip, a note, or low-signal.

Videos under 60 seconds (TikToks, YouTube Shorts) take a **fast path**: the whole video is uploaded once to Gemini's File API and summarized in a single call.

The flow as a diagram:

```
START → ingest → transcribe → probe_short
  ├── whole_video_oneshot ─────────────────► classify → fuse → END   (Gemini short path)
  └── probe_kind
        ├── summary ─────────────────────── ► classify → fuse → END   (audio-first)
        └── target → keyframes → vision ──► classify → fuse → END    (visual)
```

### Three-layer architecture (for the curious)

The pipeline is split into three layers so that when a better model ships in 2027, or LangChain publishes a breaking v2, only the middle layer changes. Stage code never imports a provider SDK directly — it calls into `model_client.py`, which is the only place in the codebase that knows about Gemini, Claude, or Ollama.

```
┌──────────────────────────────────────────────────────┐
│  pipeline.py  — LangGraph StateGraph (narrow)        │
│    nodes: ingest, transcribe, probe_short, probe_kind│
│           target, keyframes, vision, summary,        │
│           classify, fuse                             │
├──────────────────────────────────────────────────────┤
│  model_client.py  — portability seam                 │
│    resolve_model_id / build_chat_model               │
│    invoke_structured (json_repair fallback)          │
│    invoke_vision (cross-provider multimodal)         │
│    sliding-window rate limiter                       │
├──────────────────────────────────────────────────────┤
│  LangChain chat wrappers (swappable)                 │
│    langchain-google-genai | langchain-anthropic |    │
│    langchain-ollama                                  │
└──────────────────────────────────────────────────────┘
```

See [`docs/architecture.md`](docs/architecture.md) for the full design rationale (including why LangGraph is narrow here and not used for agents/tools).

## Configuration

### Tier presets

| `--tier` | Targeting | Vision | Quota headroom |
|---|---|---|---|
| `lite` (default) | `gemini-flash-lite-latest` | `gemini-flash-lite-latest` | ~100 videos/day on the free 500 RPD |
| `pro` | `gemini-flash-lite-latest` | `gemini-flash-latest` | 20 RPD cap on Flash |
| `max` | `gemini-flash-lite-latest` | `claude-opus-4-7` | Uses Claude quota |
| `--offline` | `qwen2.5vl:3b` (Ollama) | `qwen2.5vl:3b` | Local, slow |

### Precedence

Model resolution walks this list top-down:

1. `--model <provider:model>` CLI flag (vision only)
2. `LEARN_VIDEO_MODEL` env var (vision only)
3. `config.toml` `[models]` table
4. Tier default from `config.TIER_MODELS`

Edit `config.toml` in the repo root — it's commented and safe to copy into `~/.claude/scripts/learn_video/config.toml` for user-scope overrides.

### Flags

```
--tier=lite|pro|max         # Quality preset (default: lite)
--model=<provider:model>    # Override vision model (highest precedence)
--offline                   # Route to local Ollama
--fresh                     # Bypass cache for this run
--short                     # Force whole-video File API upload (fails if >60s)
--notes-only                # Skip /learn-eval handoff
```

### Cache

Artifacts live under `~/.claude/cache/learn-video/<video-id>/`:

```
meta.json       # duration, tier, model ids used, timestamps
video.*         # downloaded video (360p/480p/720p per duration)
video.en.vtt    # platform captions if available
transcript.json # deduped text + timestamped segments
targets.json    # [{t, why}]
frames/         # extracted keyframes
frames/probe/   # probe-stage sample frames
fused.md        # final timeline
```

Manage it:

```bash
python -m learn_video.cli cache-info
python -m learn_video.cli cache-clean <video-id>
python -m learn_video.cli cache-clean all
```

## Demo results

A batch run on 12 URLs (April 2026) from mixed sources:

| Source | Length | Kind | Form | Notes |
|---|---|---|---|---|
| YT `ybSWI2cZzIU` | – | visual | **skill** | Claude + Ghidra MCP reverse engineering |
| YT `W4EwfEU8CGA` | 2h 39min | visual | **skill** | 1M req/sec load-test (sliding window: 10 passes → 25 targets) |
| YT `iX8g4LqF8p8` | 21 min | visual | **skill** | 7 authentication concepts |
| YT `C842vFY5kRo` | ~2h | visual | **skill** | System design + API (9-window pass) |
| Short `Yj9qOWnipTQ` | 1.0 min | visual | note | Data pipeline overview (short path) |
| Short `b4TpO9pYpqk` | 1.0 min | visual | **skill** | 5 API performance tips (short path) |
| TT `7593…462` | 1.6 min | visual | **rule** | Keep abstraction levels consistent |
| TT `7617…054` | 1.5 min | visual | **rule** | Highest-level function at top |
| TT `7617…470` | 1.3 min | visual | **rule** | Vertical whitespace for readability |
| TT `7618…422` | 1.6 min | visual | **rule** | Declare vars close to usage |
| TT `7620…534` | 1.9 min | visual | **rule** | Expose behavior, not data |
| TT `7594…998` | 1.1 min | visual | **skill** | Replace switches with polymorphism |

**Distribution**: 7 skills / 5 rules / 1 note / 0 discard. Full fused output for each is in [`docs/examples.md`](docs/examples.md).

## Requirements

| Tool | Purpose |
|---|---|
| Python 3.13 (3.11+) | runtime |
| `ffmpeg` | keyframe extraction |
| `yt-dlp` (via pip) | video download across 1800+ sites |
| `faster-whisper small.en` | captions fallback (auto-downloads on first use, ~460MB) |
| `GEMINI_API_KEY` | default `lite`/`pro` tiers |
| `ANTHROPIC_API_KEY` | `--tier=max` or `--model anthropic:*` |
| Ollama + `qwen2.5vl:3b` | `--offline` only |

## Status

- 76 unit tests, all green
- Verified end-to-end on 12 live URLs (6 TikToks, 4 YouTube standard, 2 YouTube Shorts)
- Long-video path verified on a 2h 39min talk (10 sliding windows, 25 targets)
- Short-video File API path verified on 2 YouTube Shorts

Tracked in [`CHANGELOG.md`](CHANGELOG.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). The short version: keep stage code provider-agnostic, keep `model_client.py` as the sole LangChain importer, and add a test for every new stage behavior.

## License

MIT — see [`LICENSE`](LICENSE).

## Acknowledgements

Built on top of [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper), [`LangGraph`](https://langchain-ai.github.io/langgraph/), and [`LangChain`](https://langchain.com/). Designed for [Claude Code](https://claude.com/claude-code) and the Everything Claude Code (ECC) plugin ecosystem.
