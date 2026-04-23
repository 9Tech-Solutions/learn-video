# Changelog

All notable changes to this project are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Ruff + mypy** wired in as the project's static-analysis tools. Configured in `pyproject.toml` with a moderate rule set (`E`, `F`, `W`, `I`, `B`, `UP`, `SIM`) at line length 100.
- **CI lint job** — new `lint + typecheck` job in `.github/workflows/tests.yml`, runs on every push / PR before the 6-cell test matrix.
- `ruff` and `mypy` added to the `[dev]` extras group.

### Changed

- Replaced `setattr(model, "_lv_model_id", ...)` with direct attribute assignment (ruff `B010`).
- Collapsed a nested `if` in `transcribe._strip_overlap` into a single condition (ruff `SIM102`).
- Replaced a `try/except/pass` with `contextlib.suppress(Exception)` in `model_client.tag_model` (ruff `SIM105`).
- Replaced `typing.Type` with built-in `type` in `invoke_structured` (ruff `UP006`).
- Removed 14 redundant `# type: ignore[import-not-found]` pragmas — provider imports are now covered by `[[tool.mypy.overrides]]` with `ignore_missing_imports = true`.
- Tightened test assertions from bare `assertRaises(Exception)` to `assertRaises(ValidationError)` (ruff `B017`).
- Narrowed `init_chat_model` call to use an explicit `temperature=0` keyword so mypy can match an overload.
- `VisionInput` content lists annotated as `list[str | dict[str, Any]]` so they satisfy LangChain's covariant `HumanMessage` content parameter.
- Gemini File API code handles `uploaded.name` and `info.uri` Optional-ness explicitly.
- `cli._run` casts the input dict to `PipelineState` (TypedDict) for mypy.

## [0.2.0] — 2026-04-23

Installer rewrite for cross-platform UX. No runtime pipeline changes.

### Added

- **`scripts/install.py`** — stdlib-only interactive installer with a six-step flow (prereqs → venv → pack → install → keys → smoke-test) plus a progress spinner, hidden-input key prompt, and atomic `.env` writing. Runs on Windows / macOS / Linux from one codepath.
- **`setup.ps1`** — PowerShell shim that delegates to the Python installer (matches the existing `setup.sh` behavior).
- **`[project.optional-dependencies]`** groups `lite`, `full`, and `dev` in `pyproject.toml`. `pip install .[lite]` now pulls only the Gemini stack (~200 MB) instead of the full 350 MB; `full` adds Anthropic + Ollama; `dev` adds pytest + coverage.
- **Non-interactive flags** for CI / Docker use: `--yes`, `--pack={lite,full,dev}`, `--no-venv`, `--venv-path`, `--gemini-key`, `--anthropic-key`, `--skip-smoke-test`, `--quiet`.
- **`learn_video/tests/test_installer.py`** — 28 new tests covering prereq detection, pack parsing, venv-path resolution, atomic env-file writing, spinner behavior, and argparse.
- **CI installer smoke test** — new step in `.github/workflows/tests.yml` that runs the installer non-interactively on every matrix cell, catching cross-platform regressions before release.

### Changed

- **`setup.sh`** reduced from 69 lines to a ~20-line shim that execs the Python installer. Same invocation; much smaller surface.
- **`pyproject.toml`** top-level `dependencies` now contains only the base-runtime needs (`pydantic`, `tenacity`, `json-repair`, `python-dotenv`, `tomli`). Provider SDKs live in extras groups.
- **`requirements.txt`** kept as a full-install shortcut with a header comment pointing at the extras workflow.
- **`README.md`** Quickstart section rewritten to lead with the installer walk-through, with non-interactive and manual install paths documented below.

### Fixed

- Windows users without git-bash could not run `setup.sh`. `setup.ps1` + the Python installer fix this.

### Testing

- 74 → 102 unit tests (all green). New tests are hermetic — no subprocess or network calls; interactive flows are not exercised (covered by the CI smoke test and manual verification).

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
