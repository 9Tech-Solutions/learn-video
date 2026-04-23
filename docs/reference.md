# Reference

## CLI

```
python -m learn_video.cli <subcommand> [args]

Subcommands:
  run <url>               execute pipeline on a URL
  cache-info              list cached videos
  cache-clean <id>|all    remove one or all cache dirs
```

### `run` flags

| Flag | Default | Purpose |
|---|---|---|
| `--tier=lite\|pro\|max` | `lite` | Quality preset |
| `--model=<provider:model>` | (unset) | Override vision model (highest precedence after CLI) |
| `--offline` | off | Route to local Ollama (`qwen2.5vl:3b`) |
| `--fresh` | off | Delete cache for this video and re-run every stage |
| `--short` | off | Force whole-video File API upload; fails if video > 60 s |
| `--notes-only` | off | Skip `/learn-eval` handoff (produce `fused.md` and stop) |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success; `fused.md` path on stdout |
| 2 | `ConfigurationError` (missing API key, bad input) |
| 3 | `EnvironmentError_` (`ffmpeg` / `yt-dlp` not installed) |
| 4 | `TargetError` (DRM, deleted, region-locked) |
| 5 | `TransientError` after retries |
| 6 | Other `LearnVideoError` |

## Environment variables

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini models (default tiers) |
| `ANTHROPIC_API_KEY` | `--tier=max` or `--model anthropic:*` |
| `LEARN_VIDEO_MODEL` | Default vision model (CLI `--model` wins over this) |
| `LEARN_VIDEO_CONFIG` | Path override for `config.toml` |
| `HF_HUB_DISABLE_SYMLINKS_WARNING=1` | Silence Whisper's Windows cache warning |

A `.env` file in the repo root is auto-loaded when `python-dotenv` is installed.

## `config.toml`

```toml
[defaults]
# tier = "lite"                         # lite | pro | max
# notes_only = false

# [models]
# targeting = "google_genai:gemini-flash-lite-latest"
# vision    = "anthropic:claude-opus-4-7"

# [rate_limits]
# flash_lite_min_spacing_s = 4.5
# max_retries = 3
# backoff_cap_s = 60

# [whisper]
# model = "small.en"
# compute_type = "int8"
```

Precedence (highest to lowest):
1. CLI `--model=...` flag (vision only)
2. `LEARN_VIDEO_MODEL` env var (vision only)
3. `[models]` table in `config.toml`
4. `TIER_MODELS` default for the selected `--tier`

Targeting always stays on Flash Lite regardless of CLI / env overrides; those only reroute vision. Rationale: targeting is a cheap text task; burning a premium quota on it is almost always wrong.

## Python API

```python
from learn_video.pipeline import run

final_state = run({
    "url": "https://www.youtube.com/watch?v=<id>",
    "tier": "lite",
    "offline": False,
    "model_override": None,
    "force_short": False,
    "fresh": False,
    "notes_only": False,
})

print(final_state["final_md_path"])
print(final_state["recommended_form"])
print(final_state["video_kind"])
```

`final_state` is a `PipelineState` TypedDict; see `state.py` for the full schema.

## fused.md format

```markdown
# <video title>

- **recommended-form:** `<skill|rule|tip|note|discard>`, <one-line reason>
- **video-kind:** `<visual|audio|mixed>` (confidence <0-1>), <one-line reason>
- **URL:** <url>
- **Video ID:** `<id>`
- **Targeting model:** `<provider:model>`
- **Vision model:** `<provider:model>`

## Timeline

### [mm:ss]

**AUDIO:** <transcript window around this timestamp>

**VISUAL:** <what's on screen: code, diagram, UI, slide>

**FUSED:** <single-sentence reusable note>

### [mm:ss]
...
```

Parsers downstream (e.g. `/learn-eval`) should key off `recommended-form:` and `video-kind:` lines; they are always present and appear before the `## Timeline` header.
