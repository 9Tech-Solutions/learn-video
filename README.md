# learn-video

[![tests](https://github.com/9Tech-Solutions/learn-video/actions/workflows/tests.yml/badge.svg)](https://github.com/9Tech-Solutions/learn-video/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![skills.sh](https://img.shields.io/badge/skills.sh-9Tech--Solutions%2Flearn--video-black)](https://skills.sh/9Tech-Solutions/learn-video/learn-video)

> Extract reusable knowledge from video platforms. Not transcripts — **fused audio + visual notes** aligned to the moment a concept is taught.

`learn-video` is a Claude Code skill that runs a 6-stage pipeline over a YouTube, TikTok, or any `yt-dlp`-supported URL and produces a `fused.md` timeline designed to hand off to `/learn-eval`. It reads the transcript to pick which timestamps need a frame, extracts just those keyframes with `ffmpeg`, and asks a vision model to fuse each frame with its transcript window. The output is organised as `AUDIO / VISUAL / FUSED` blocks — the `FUSED:` line on each block is a single-sentence reusable note.

It is **model-portable by design**. The only module that imports `langchain-*` is `model_client.py`. A LangChain v2 break, a migration to LiteLLM, or a 2027 model release touches that one file. Stage code stays unchanged.

## Why this exists

A survey of [skills.sh](https://skills.sh/) and five adjacent registries (April 2026) returned ~10 YouTube-related skills and zero that do audio-visual fused knowledge extraction. The ecosystem treats video as "transcript with metadata." `learn-video` occupies the empty slot.

| Capability | Transcript skills | YouTube-clipper | **learn-video** |
|---|:---:|:---:|:---:|
| YouTube transcript | ✅ | ✅ | ✅ |
| Multi-platform (TikTok, Vimeo, 1800+ sites) | ❌ | ❌ | ✅ |
| Whisper fallback when captions missing | ❌ | ❌ | ✅ |
| VTT scroll-caption dedup | ❌ | ❌ | ✅ |
| LLM-guided keyframe targeting | ❌ | ❌ | ✅ |
| Vision model on frames | ❌ | ❌ | ✅ |
| Audio + visual FUSED blocks | ❌ | ❌ | ✅ |
| Video-kind probe (visual / audio / mixed) | ❌ | ❌ | ✅ |
| Short-video fast path (Gemini File API) | ❌ | ❌ | ✅ |
| Sliding-window targeting for 1–3h videos | ❌ | ❌ | ✅ |
| Model portability seam (LangChain/LangGraph adapter) | ❌ | ❌ | ✅ |
| Tiered quality + offline Ollama path | ❌ | ❌ | ✅ |
| `recommended-form` classification | ❌ | ❌ | ✅ |
| Per-provider sliding-window rate limiter | ❌ | ❌ | ✅ |
| Concurrent vision with RPM enforcement | ❌ | ❌ | ✅ |

## Example output

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

## How it works

```
START → ingest → transcribe → probe_short
  ├── whole_video_oneshot ─────────────────► classify → fuse → END   (Gemini short path)
  └── probe_kind
        ├── summary ─────────────────────── ► classify → fuse → END   (audio-first)
        └── target → keyframes → vision ──► classify → fuse → END    (visual)
```

Three-layer architecture:

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
