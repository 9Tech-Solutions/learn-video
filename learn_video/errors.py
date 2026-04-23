"""Typed exception taxonomy (see plan §11).

Four classes so the CLI/logger can decide retry vs fail-fast vs onboard
without string-sniffing arbitrary exception text.
"""

from __future__ import annotations


class LearnVideoError(Exception):
    """Base. Don't raise directly — pick a subclass."""


class TransientError(LearnVideoError):
    """Auto-retry. Examples: 429, TimeoutError, network blip."""


class ConfigurationError(LearnVideoError):
    """Fail fast and print fix hint. Example: missing API key."""

    def __init__(self, message: str, fix_hint: str | None = None) -> None:
        super().__init__(message)
        self.fix_hint = fix_hint


class EnvironmentError_(LearnVideoError):
    """Fail fast and print install command. Example: ffmpeg missing.

    Trailing underscore to avoid shadowing the builtin ``EnvironmentError``.
    """

    def __init__(self, message: str, install_cmd: str | None = None) -> None:
        super().__init__(message)
        self.install_cmd = install_cmd


class TargetError(LearnVideoError):
    """Unrecoverable — don't retry. Examples: DRM block, deleted video."""
