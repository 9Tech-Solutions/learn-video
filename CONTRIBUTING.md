# Contributing to learn-video

Thanks for considering a contribution. This doc covers the architectural invariants the codebase protects, the testing bar, and the PR flow.

## Architectural invariants

These are load-bearing. Violating them defeats the portability story that justifies this skill's existence:

1. **Only `learn_video/model_client.py` imports `langchain-*` or provider SDKs.** Every stage module (`ingest`, `transcribe`, `probe`, `target`, `keyframes`, `vision`, `summary`, `classify`, `fuse`) calls into `model_client` through `build_chat_model`, `invoke_structured`, and `invoke_vision`. If you find yourself adding `from langchain_google_genai import ...` in a stage, stop — add the feature to `model_client` and call into it instead.

2. **Stages communicate only via `PipelineState`** (defined in `state.py`). No cross-stage imports of private helpers. If two stages need to share logic, extract it to a utility module (see `ffmpeg_util.py` for the pattern).

3. **Every stage is idempotent via its cache artifact.** Re-running the pipeline on the same video with a warm cache must be free (no LLM calls). If you add a stage, check its artifact before running and honor `--fresh`.

4. **Errors use the four-class taxonomy** (`errors.py`): `TransientError` (retryable), `ConfigurationError` (fix hint), `EnvironmentError_` (install command), `TargetError` (unrecoverable). `LearnVideoError` base class is not raised directly.

## Testing bar

- **Every new behavior ships with a unit test.** Current suite: 74+ tests, under `learn_video/tests/`. Run with `python -m unittest discover -s learn_video/tests -t .` from the repo root.
- **Pure-Python stages** (ingest format selection, cache paths, VTT dedup, target filtering, window splitting, fuse markdown, rate limiter, invoke_structured fallbacks) have full coverage and no network calls.
- **LLM-touching stages** (probe, target, vision, summary, classify) are tested with mocked `model_client` calls. Don't add tests that hit live APIs — tests must stay hermetic.
- **No integration tests against live video URLs** in CI. The README's 12-video demo is a manual smoke test run by maintainers.

## PR flow

1. Fork + branch from `main`.
2. Write the test first. See existing tests for the style.
3. Implement.
4. `python -m unittest discover -s learn_video/tests -t .` — must be green.
5. `python -m compileall -q learn_video/` — must be clean.
6. If you changed the pipeline graph in `pipeline.py`, update the diagram in `README.md` and `SKILL.md`.
7. If you touched `config.py` `TIER_MODELS`, add a note to `CHANGELOG.md`.
8. Open the PR with: what changed, why, and which tests prove it.

## Common extensions

- **New provider** (Mistral, Cohere, xAI, …): add it to `TIER_MODELS` in `config.py`, register a rate limit in `model_client._RATE_LIMITS`, optionally extend `_retryable_exception_types()` to include the provider SDK's transient exceptions. Stage code should not change.
- **New stage**: add a module under `learn_video/`, wire it into `pipeline.py`'s StateGraph, add fields to `PipelineState` in `state.py`, and include a cache-hit fast path.
- **New downstream form** for `recommended-form`: edit `state.py` `RecommendedForm` literal, update the prompt in `classify.py`, and extend the handoff logic in the slash command.

## Style

- Type hints on public functions. `from __future__ import annotations` at the top of every module.
- Pydantic models for structured LLM output. Make list fields `Field(default_factory=list)` so empty-response fallbacks don't crash validation.
- Docstrings on modules explaining their role in the pipeline. Function docstrings only when the _why_ isn't obvious from the name and types.
- Line limit: soft 100 chars. Hard 120.

## Questions

Open a GitHub issue with the `question` label, or ask in the PR if it's scoped to that change.
