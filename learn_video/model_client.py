"""model_client — the portability seam.

ONLY file that imports ``langchain-*`` packages. Stage code uses:

    model = build_chat_model(model_id)
    targets = invoke_structured(model, TargetList, messages)
    out    = invoke_vision(model, VisionInput(text=..., image_b64=...))

If LangChain v2 breaks, if we migrate to LiteLLM, if a 2027 provider shows
up — only this file changes. Everything else is provider-agnostic.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .errors import ConfigurationError, TransientError
from .state import VisionInput

T = TypeVar("T", bound=BaseModel)

# --- Provider-level rate limiting -------------------------------------------
# Sliding-window limiter: at most ``max_requests`` in any ``window_s``-second
# window per model id. Requests that would exceed the cap block until the
# oldest timestamp in the window expires. This lets us fire N concurrent
# requests (from vision.per_frame_node parallelization) without tripping
# Gemini's 429s — earlier versions used fixed 4.5s spacing which forced
# serial execution even though the free tier allows up to 15 RPM.

# (max_requests, window_seconds). Buffered slightly below provider caps so
# transient clock skew doesn't get us 429'd.
_RATE_LIMITS: dict[str, tuple[int, float]] = {
    "google_genai:gemini-flash-lite-latest": (13, 60.0),  # provider cap 15 RPM
    "google_genai:gemini-flash-latest": (8, 60.0),         # provider cap 10 RPM
    "google_genai:gemini-3.1-flash-lite-preview": (13, 60.0),
    "google_genai:gemini-3-flash-preview": (8, 60.0),
    # Claude / Ollama: no in-process gate (plenty of headroom on personal use)
}

_RATE_LOCKS: dict[str, threading.Lock] = {}
_REQUEST_LOG: dict[str, deque[float]] = {}


def _limits_for(model_id: str) -> tuple[int, float] | None:
    return _RATE_LIMITS.get(model_id)


def _throttle(model_id: str) -> None:
    """Block until a request slot is available. Thread-safe."""
    limits = _limits_for(model_id)
    if not limits:
        return
    max_req, window_s = limits
    lock = _RATE_LOCKS.setdefault(model_id, threading.Lock())
    with lock:
        log = _REQUEST_LOG.setdefault(model_id, deque())
        now = time.monotonic()
        while log and now - log[0] >= window_s:
            log.popleft()
        if len(log) >= max_req:
            sleep_for = window_s - (now - log[0]) + 0.05  # tiny cushion
            if sleep_for > 0:
                time.sleep(sleep_for)
            # Re-prune post-sleep
            now = time.monotonic()
            while log and now - log[0] >= window_s:
                log.popleft()
        log.append(time.monotonic())


def _reset_rate_limiter() -> None:
    """Test-only hook — clears per-model request logs."""
    _REQUEST_LOG.clear()


# --- Retry policy ------------------------------------------------------------

def _retryable_exception_types() -> tuple[type[BaseException], ...]:
    """Build the retryable-exception tuple lazily so missing provider SDKs
    don't crash import."""
    out: list[type[BaseException]] = [TimeoutError, TransientError, ConnectionError]
    try:
        from google.api_core.exceptions import ResourceExhausted

        out.append(ResourceExhausted)
    except ImportError:  # pragma: no cover
        pass
    try:
        from google.api_core.exceptions import ServiceUnavailable

        out.append(ServiceUnavailable)
    except ImportError:  # pragma: no cover
        pass
    try:
        from anthropic import RateLimitError

        out.append(RateLimitError)
    except ImportError:  # pragma: no cover
        pass
    try:
        from anthropic import APIConnectionError

        out.append(APIConnectionError)
    except ImportError:  # pragma: no cover
        pass
    try:
        # httpx lives under langchain-google-genai's stack; covers
        # ReadError, ConnectError, RemoteProtocolError, PoolTimeout, etc.
        import httpx

        out.extend([httpx.TransportError, httpx.TimeoutException])
    except ImportError:  # pragma: no cover
        pass
    return tuple(out)


def _with_backoff(fn, *args: Any, **kwargs: Any):
    """Tenacity-style retry without importing tenacity at the call site.

    Falls back to a hand-rolled exponential-with-jitter loop when tenacity
    isn't available — keeps this module importable for unit tests that
    mock the underlying call.
    """
    try:
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_random_exponential,
        )
    except ImportError:  # pragma: no cover
        return _manual_backoff(fn, *args, **kwargs)

    types = _retryable_exception_types()

    @retry(
        wait=wait_random_exponential(multiplier=5, max=60),
        retry=retry_if_exception_type(types),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _inner():
        return fn(*args, **kwargs)

    return _inner()


def _manual_backoff(fn, *args: Any, **kwargs: Any):  # pragma: no cover - fallback
    types = _retryable_exception_types()
    delays = (5.0, 10.0, 20.0)
    last: BaseException | None = None
    for attempt, delay in enumerate(delays):
        try:
            return fn(*args, **kwargs)
        except types as exc:
            last = exc
            if attempt == len(delays) - 1:
                raise
            time.sleep(delay)
    raise last or RuntimeError("unreachable")


# --- Model construction ------------------------------------------------------

def build_chat_model(model_id: str, **kwargs: Any):
    """Build a LangChain chat model from ``<provider>:<model>`` id.

    Uses ``langchain.chat_models.init_chat_model`` so adding a new provider
    is a requirements.txt edit, not a code change here.
    """
    _verify_api_key(model_id)
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise ConfigurationError(
            "langchain not installed",
            fix_hint="pip install -r ~/.claude/scripts/learn_video/requirements.txt",
        ) from exc
    # Explicit keyword for temperature so mypy can match an overload;
    # user kwargs override the default naturally via dict-merge in call-time.
    return init_chat_model(model_id, temperature=0, **kwargs)


def _verify_api_key(model_id: str) -> None:
    provider = model_id.split(":", 1)[0]
    required = {
        "google_genai": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "anthropic": ("ANTHROPIC_API_KEY",),
        # ollama is local — no key
    }.get(provider)
    if not required:
        return
    if any(os.environ.get(k) for k in required):
        return
    raise ConfigurationError(
        f"{provider} requires one of {required}",
        fix_hint=(
            f"export {required[0]}=... (or put it in "
            "~/.claude/scripts/learn_video/.env)"
        ),
    )


# --- Invocation helpers ------------------------------------------------------

def invoke_structured(model, schema: type[T], messages) -> T:
    """Structured output with a ``json_repair`` fallback.

    Some providers (Ollama especially) return not-quite-JSON. We try the
    native ``.with_structured_output(schema)`` path first; on any parse
    failure we fall back to raw-text + ``json_repair``.
    """
    model_id = getattr(model, "_lv_model_id", None) or ""
    _throttle(model_id)

    def _call_structured():
        return model.with_structured_output(schema).invoke(messages)

    try:
        return _with_backoff(_call_structured)
    except Exception:
        # Fallback — raw text, repair, validate.
        def _call_raw():
            return model.invoke(messages)

        raw_msg = _with_backoff(_call_raw)
        content = getattr(raw_msg, "content", raw_msg)
        if isinstance(content, list):
            # Multimodal returns structured content blocks — pull the text.
            content = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        stripped = str(content).strip()
        if not stripped:
            # Empty response → try to build a zero-value instance. Works for
            # schemas whose fields all have defaults (e.g. TargetList with
            # default_factory=list). For strict schemas this re-raises with
            # the original Pydantic message intact.
            try:
                return schema()
            except Exception as exc:
                raise TransientError(
                    f"{schema.__name__}: empty response from model"
                ) from exc
        try:
            from json_repair import loads as repair_loads
        except ImportError:  # pragma: no cover
            import json as _json

            # mypy narrows repair_loads to json_repair.loads's type; stdlib
            # json.loads is a compatible callable but has a different signature.
            repair_loads = _json.loads  # type: ignore[assignment]
        repaired = repair_loads(stripped)
        if not repaired:
            # json_repair coerces unparseable text to "" or [] → same treatment
            try:
                return schema()
            except Exception as exc:
                raise TransientError(
                    f"{schema.__name__}: model returned no JSON"
                ) from exc
        return schema.model_validate(repaired)


def invoke_vision(model, vi: VisionInput, *, model_id: str | None = None):
    """Single vision call. Translates ``VisionInput`` to the portable
    ``image_url`` + data-URL shape shared by Gemini / Claude / Ollama.

    ``video_path`` is Gemini-only; we raise for other providers rather than
    silently drop the video. The pipeline gates this path on tier so it only
    fires when the provider supports it.
    """
    try:
        from langchain_core.messages import HumanMessage
    except ImportError as exc:
        raise ConfigurationError(
            "langchain-core not installed",
            fix_hint="pip install -r ~/.claude/scripts/learn_video/requirements.txt",
        ) from exc

    mid = model_id or getattr(model, "_lv_model_id", "") or ""
    _throttle(mid)

    # Annotate as a union list so it matches HumanMessage's covariant parameter
    # (list is invariant in Python's type system).
    content: list[str | dict[str, Any]] = [{"type": "text", "text": vi.text}]
    if vi.image_b64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{vi.image_b64}"},
            }
        )

    if vi.video_path:
        provider = mid.split(":", 1)[0]
        if provider != "google_genai":
            raise ConfigurationError(
                f"video_path input is Gemini-only; got provider={provider!r}",
                fix_hint="use --tier=lite or --tier=pro, or drop --short",
            )
        file_uri = _gemini_upload(Path(vi.video_path))
        content.append(
            {
                "type": "media",
                "mime_type": "video/mp4",
                "file_uri": file_uri,
            }
        )

    def _call():
        return model.invoke([HumanMessage(content=content)])

    return _with_backoff(_call)


def _gemini_upload(path: Path) -> str:
    """Upload a video via the Gemini File API and return the file URI.

    Provider-specific code — isolated to this function. If Gemini changes
    their upload API this is where we fix it.
    """
    try:
        from google import genai
    except ImportError as exc:
        raise ConfigurationError(
            "google-genai SDK not installed (needed for raw-video upload)",
            fix_hint="pip install google-genai",
        ) from exc
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ConfigurationError(
            "GOOGLE_API_KEY / GEMINI_API_KEY required for video upload",
            fix_hint="export GEMINI_API_KEY=...",
        )
    client = genai.Client(api_key=key)
    uploaded = client.files.upload(file=str(path))
    uploaded_name = uploaded.name or ""
    if not uploaded_name:
        raise TransientError("Gemini file upload returned no name")
    # Poll until ACTIVE — Gemini's video processing is typically 30s–4min
    # depending on length and current load. Start at 2s, back off to 5s.
    deadline = time.monotonic() + 300.0
    delay = 2.0
    last_state = ""
    while time.monotonic() < deadline:
        info = client.files.get(name=uploaded_name)
        # state may be an enum, nested object, or plain string across SDK versions.
        raw_state = getattr(info, "state", None)
        state_str = (
            getattr(raw_state, "name", None)
            if raw_state is not None and not isinstance(raw_state, str)
            else raw_state
        ) or ""
        # Some SDK builds stringify enums as "FILESTATE.ACTIVE" — take the
        # tail after the last dot so we compare on the plain name.
        last_state = str(state_str).upper().rsplit(".", 1)[-1]
        if last_state == "ACTIVE":
            return info.uri or ""
        if last_state == "FAILED":
            raise TransientError(f"Gemini file processing FAILED: {uploaded_name}")
        time.sleep(delay)
        delay = min(5.0, delay * 1.3)
    raise TransientError(
        f"Gemini file upload stuck in {last_state or 'UNKNOWN'} after 5min: {uploaded_name}"
    )


def tag_model(model, model_id: str):
    """Stamp a model instance with its id so ``_throttle`` can key on it."""
    import contextlib
    with contextlib.suppress(Exception):  # pragma: no cover - some SDK objects reject setattr
        model._lv_model_id = model_id
    return model
