"""Config loader + model-id precedence resolver.

Precedence (highest → lowest):
  1. ``--model`` CLI flag              (applies to vision only)
  2. ``LEARN_VIDEO_MODEL`` env var     (applies to vision only)
  3. ``config.toml`` ``[models]`` table
  4. Tier default from ``TIER_MODELS``
"""

from __future__ import annotations

import os

# Python 3.11+ has tomllib in stdlib; older installs use tomli.
import tomllib as _toml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import Role, Tier


def _resolve_config_path() -> Path | None:
    """Find ``config.toml`` without hardcoding install layout.

    Checks, in order:
      1. ``LEARN_VIDEO_CONFIG`` env var (explicit override)
      2. Same directory as this module (legacy in-package layout)
      3. Parent directory (repo-root layout when installed via pip)
      4. ``~/.claude/scripts/learn_video/config.toml`` (slash-command install)
    """
    env = os.environ.get("LEARN_VIDEO_CONFIG")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    here = Path(__file__).resolve().parent
    for candidate in (
        here / "config.toml",
        here.parent / "config.toml",
        Path.home() / ".claude" / "scripts" / "learn_video" / "config.toml",
    ):
        if candidate.exists():
            return candidate
    return None


CONFIG_PATH: Path | None = _resolve_config_path()

# Tier → (role → model_id). See plan §3.
# Use the `-latest` aliases: Google rotates them as new models ship, so the
# tier map survives model promotions without code edits. Current pointers
# (Apr 2026): flash-lite-latest → 3.1 Flash Lite, flash-latest → 3 Flash.
TIER_MODELS: dict[Tier, dict[Role, str]] = {
    "lite": {
        "targeting": "google_genai:gemini-flash-lite-latest",
        "vision": "google_genai:gemini-flash-lite-latest",
    },
    "pro": {
        "targeting": "google_genai:gemini-flash-lite-latest",
        "vision": "google_genai:gemini-flash-latest",
    },
    "max": {
        "targeting": "google_genai:gemini-flash-lite-latest",
        "vision": "anthropic:claude-opus-4-7",
    },
}

OFFLINE_MODELS: dict[Role, str] = {
    "targeting": "ollama:qwen2.5vl:3b",
    "vision": "ollama:qwen2.5vl:3b",
}

# Tiers that can ingest raw short-video via the File API (Gemini).
# Claude/Ollama can't, so --short falls back to keyframe path on max/offline.
SHORT_PATH_TIERS: frozenset[Tier] = frozenset({"lite", "pro"})


@dataclass(frozen=True)
class LoadedConfig:
    tier_default: Tier
    model_overrides: dict[Role, str]       # from [models] table
    notes_only_default: bool
    rate_limits: dict[str, Any]
    whisper: dict[str, Any]


def load() -> LoadedConfig:
    data: dict[str, Any] = {}
    if _toml is not None and CONFIG_PATH is not None and CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("rb") as fh:
                data = _toml.load(fh)
        except Exception:
            data = {}
    defaults = data.get("defaults", {}) if isinstance(data, dict) else {}
    models = data.get("models", {}) if isinstance(data, dict) else {}
    rate_limits = data.get("rate_limits", {}) if isinstance(data, dict) else {}
    whisper = data.get("whisper", {}) if isinstance(data, dict) else {}

    tier = defaults.get("tier", "lite")
    if tier not in TIER_MODELS:
        tier = "lite"

    overrides: dict[Role, str] = {}
    for role in ("targeting", "vision"):
        val = models.get(role)
        if isinstance(val, str) and val:
            overrides[role] = val

    return LoadedConfig(
        tier_default=tier,
        model_overrides=overrides,
        notes_only_default=bool(defaults.get("notes_only", False)),
        rate_limits=dict(rate_limits),
        whisper=dict(whisper),
    )


def resolve_model_id(
    *,
    role: Role,
    tier: Tier,
    offline: bool,
    model_override: str | None,
    loaded: LoadedConfig | None = None,
) -> str:
    """Apply the 4-step precedence to pick the model id for this call."""
    loaded = loaded or load()

    # 1. --model flag (vision only; targeting stays on Flash Lite, cheap text)
    if role == "vision" and model_override:
        return model_override

    # 2. env var (vision only)
    if role == "vision":
        env = os.environ.get("LEARN_VIDEO_MODEL")
        if env:
            return env

    # 3. config.toml [models]
    if role in loaded.model_overrides:
        return loaded.model_overrides[role]

    # 4. tier default (or offline table)
    if offline:
        return OFFLINE_MODELS[role]
    return TIER_MODELS[tier][role]
