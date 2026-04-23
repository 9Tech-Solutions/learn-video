# Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] — 2026-04-23

First public release. Verified end-to-end on 12 live URLs (6 TikToks, 4 YouTube, 2 YouTube Shorts) with a 2h 39min talk exercising the sliding-window path.

### Pipeline

- 6-stage canonical flow: `ingest` → `transcribe` → `target` → `keyframes` → `vision` → `fuse`.
- Conditional short-video fast path: videos ≤60s on Gemini-capable tiers route to `whole_video_oneshot` (single Gemini File API upload).
- Video-kind probe (`visual | audio | mixed`) samples 5 frames and routes audio-first videos to a transcript-only `summary` stage.
- Post-fusion `classify` stage suggests `recommended-form: skill | rule | tip | note | discard` for `/learn-eval` handoff.
- Sliding-window targeting for videos >25 min (15-minute windows, 30 s overlap).
- 6-way concurrent vision fan-out under a sliding-window rate limiter (13 req / 60 s on Flash Lite).

### Model portability

- `model_client.py` is the sole LangChain importer. `TIER_MODELS` in `config.py` drives tier → model mapping.
- Structured output via `with_structured_output()` with `json_repair` fallback and empty-response short-circuit.
- Portable `image_url` + data-URL multimodal shape across Gemini, Claude, and Ollama.
- Gemini File API upload (video-only) isolated to `_gemini_upload` in `model_client.py`.

### Caching

- Artifact-based cache at `~/.claude/cache/learn-video/<video-id>/`; stage-level idempotency.
- `cache-info` and `cache-clean` CLI subcommands.
- VTT scroll-caption overlap stripping (`_strip_overlap`) — removes the triplicate-text artifact in YouTube auto-captions.

### Resilience

- Four-class error taxonomy: `TransientError`, `ConfigurationError`, `EnvironmentError_`, `TargetError`.
- Tenacity retry (5/10/20 s with jitter, max 3) covering `ResourceExhausted`, `ServiceUnavailable`, `RateLimitError`, `APIConnectionError`, `httpx.TransportError`, `httpx.TimeoutException`.
- Per-frame vision failures in the concurrent fan-out log a warning and continue instead of killing the whole run.
- Per-window target failures continue with lighter target lists.
- Duration-aware format selector: 720p ≤30 min, 480p 30–90 min, 360p >90 min; download timeout scales with duration (15 min–1 h).
- Gemini File API poll budget: 5 min, exponential backoff; handles `FILESTATE.ACTIVE` enum stringification.

### Testing

- 76 unit tests, all green.
- Coverage: state schemas, cache paths, VTT + overlap dedup, config precedence, target windowing + filtering, rate limiter (burst, cap, thread-safety), empty-response fallbacks, format + timeout selectors, vision parsing, summary formatters, fuse headers, logging formatter, probe path math, error taxonomy.
