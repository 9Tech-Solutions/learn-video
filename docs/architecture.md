# Architecture

## Three-layer design

```
┌──────────────────────────────────────────────────────┐
│  pipeline.py   (LangGraph StateGraph, narrow)        │
│    • 2 conditional edges: short-path, kind-path      │
│    • nodes: ingest, transcribe, probe_short,         │
│             probe_kind, target, keyframes, vision,   │
│             summary, whole_video_oneshot, classify,  │
│             fuse                                     │
├──────────────────────────────────────────────────────┤
│  model_client.py   (portability seam)                │
│    • resolve_model_id(role, ctx) → str               │
│    • build_chat_model(model_id) → BaseChatModel      │
│    • invoke_structured(model, schema, messages) → T  │
│    • invoke_vision(model, vision_input)              │
│    • tenacity + sliding-window rate limit            │
├──────────────────────────────────────────────────────┤
│  LangChain chat wrappers (swappable)                 │
│    langchain-google-genai, langchain-anthropic,      │
│    langchain-ollama                                  │
└──────────────────────────────────────────────────────┘
```

If LangChain v2 breaks or we migrate to LiteLLM / direct SDKs later, only `model_client.py` changes. Stage code never imports `ChatGoogleGenerativeAI`, `HumanMessage`, or any provider-specific type.

## Graph shape

```
START → ingest → transcribe → probe_short
  ├── whole_video_oneshot ─────────────────► classify → fuse → END   (short, Gemini-capable)
  └── probe_kind
        ├── summary ─────────────────────── ► classify → fuse → END   (audio-first)
        └── target → keyframes → vision ──► classify → fuse → END    (visual tutorial)
```

Two conditional edges:

- `probe_short`: routes to the short-video fast path (single Gemini File API upload) when `duration ≤ 60 s` AND `tier ∈ {lite, pro}` AND not `--offline`.
- `probe_kind`: routes to `summary` when the 5-frame classifier returns `audio` with ≥ 0.65 confidence; otherwise to the visual path.

Both routers have explicit fall-backs: unknown kinds take the visual path, low confidence takes the visual path. "Default to doing the full pipeline" means we never silently underprocess a video.

## Why LangGraph here and not just LangChain

LangChain alone is not the portability strategy; the strategy is `model_client.py`. LangGraph is used narrowly because the pipeline has real graph semantics:

- Conditional edges (short-path, kind-path) live cleanly in a StateGraph.
- Future retries ("vision 429 → fallback to `pro` tier and retry just that frame" or "targets empty → widen prompt and retry window") are natural graph edges.
- Durable execution (LangGraph checkpointers) is available if we want in-flight resumability later, but isn't v1: artifact-based cache IS our checkpointer.

We do **not** use LangChain agents, tool-calling abstractions, or chain composition; those are overkill for a linear-ish pipeline and they leak LangChain semantics into stage code.

## State schema

`PipelineState` (in `state.py`) is a `TypedDict(total=False)`:

- **Inputs**: `url`, `tier`, `offline`, `model_override`, `force_short`, `fresh`, `notes_only`.
- **Populated during run**: `video_id`, `cache_dir`, `title`, `duration_s`, `is_short_video`, `video_path`, `captions_path`, `transcript`, `transcript_source`, `targets`, `frames`, `fused_blocks`, `final_md_path`.
- **Classification**: `video_kind`, `video_kind_confidence`, `video_kind_reason`, `recommended_form`, `recommended_form_reason`.
- **Audit trail**: `targeting_model_id`, `vision_model_id`, `probe_model_id`.

Pydantic models carry the structured payloads:

- `Target(t, why)` and `TargetList(targets: list[Target])`: `targets` has `default_factory=list` so empty responses don't crash validation.
- `FrameRef(t, image_path, transcript_window)`
- `FusedBlock(t, audio, visual, fused)`
- `VisionInput(text, image_b64, video_path)`: exactly one of `image_b64` / `video_path` is set per call; `video_path` is Gemini-only.

## Cross-provider multimodal

`invoke_vision` translates `VisionInput` into the portable content shape that works across Gemini, Claude, and Ollama:

```python
HumanMessage(content=[
    {"type": "text", "text": prompt},
    {"type": "image_url",
     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
])
```

Raw video (`video_path`) is **not portable**. The adapter raises `ConfigurationError` for non-Gemini providers instead of silently dropping the video. The pipeline routes around this by gating the short-video fast path on Gemini-capable tiers.

## Rate limiting

Sliding-window in-process limiter per model id:

```python
_RATE_LIMITS = {
    "google_genai:gemini-flash-lite-latest": (13, 60.0),  # cap 15 RPM, buffered
    "google_genai:gemini-flash-latest":       (8,  60.0),  # cap 10 RPM, buffered
    # Claude / Ollama: no in-process gate (plenty of headroom)
}
```

`_throttle(model_id)` keeps a `deque[float]` of recent request timestamps per model; if adding one would exceed the cap, it sleeps until the oldest entry in the window expires. The deque supports concurrent vision fan-out: 6 threads can contend on Flash Lite safely, provider is never asked to do more than 13 req / 60 s.

## Retry policy

`_retryable_exception_types()` builds the tuple lazily (missing provider SDKs don't crash import):

- `TimeoutError`, `TransientError`, `ConnectionError`
- `google.api_core.exceptions.ResourceExhausted`, `ServiceUnavailable`
- `anthropic.RateLimitError`, `APIConnectionError`
- `httpx.TransportError`, `httpx.TimeoutException`

Tenacity retries 3 times with `wait_random_exponential(multiplier=5, max=60)`. Per-frame vision failures don't kill the run; they log a warning and drop that one block.

## Caching and idempotency

`~/.claude/cache/learn-video/<video-id>/`:

```
meta.json       # duration, tier, timestamps, model ids used, classifications
video.*         # downloaded video file (extension depends on yt-dlp muxing)
video.en.vtt    # platform captions if available
transcript.json # deduped text + timestamped segments + source tag
targets.json    # [{t, why}] + model_id that produced them
frames/         # extracted keyframes, chronologically sortable filenames
frames/probe/   # 5 sample frames from the probe stage
fused.md        # final timeline markdown
```

Every stage checks its artifact before running. `--fresh` deletes `<video-id>/` first. Stage-level idempotency IS retry idempotency: a 429 retry re-enters the pipeline and hits the cache rather than re-calling the API.
