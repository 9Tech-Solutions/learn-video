#!/usr/bin/env python3
"""learn-video interactive installer.

Works on Windows, macOS, and Linux. Stdlib only, no deps before the deps
are installed. Shims ``setup.sh`` and ``setup.ps1`` delegate here.

Usage:
    python scripts/install.py               # full interactive flow
    python scripts/install.py --yes \\
        --pack=lite \\
        --gemini-key=$GEMINI_API_KEY        # fully non-interactive (CI)
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from itertools import cycle
from pathlib import Path

# Exit codes mirror learn_video.errors conventions:
# 0=ok, 2=config, 3=environment, 5=generic failure.
EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_ENV = 3
EXIT_FAIL = 5

PACK_CHOICES = ("lite", "full", "dev")
MIN_PYTHON = (3, 11)

# Spinner frames: Unicode first, ASCII fallback for dumb terminals.
SPINNER_UTF8 = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SPINNER_ASCII = "|/-\\"

# Box drawing: Unicode first, ASCII fallback.
BOX_UTF8 = {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "─", "v": "│"}
BOX_ASCII = {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|"}

CHECK_UTF8, CROSS_UTF8, ARROW_UTF8 = "✓", "✗", "→"
CHECK_ASCII, CROSS_ASCII, ARROW_ASCII = "[ok]", "[x]", "->"


# ---------------------------------------------------------------------------
# Terminal capability detection
# ---------------------------------------------------------------------------

def _is_utf8() -> bool:
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


def _is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _check() -> str: return CHECK_UTF8 if _is_utf8() else CHECK_ASCII
def _cross() -> str: return CROSS_UTF8 if _is_utf8() else CROSS_ASCII
def _arrow() -> str: return ARROW_UTF8 if _is_utf8() else ARROW_ASCII


# ---------------------------------------------------------------------------
# Minimal printing: stderr only, mirrors learn_video/logging_.py style
# ---------------------------------------------------------------------------

_STEP_COUNT = 6


def _step(n: int, title: str) -> None:
    print(f"\n[{n}/{_STEP_COUNT}] {title}", file=sys.stderr, flush=True)


def _ok(msg: str) -> None:
    print(f"  {_check()} {msg}", file=sys.stderr, flush=True)


def _bad(msg: str) -> None:
    print(f"  {_cross()} {msg}", file=sys.stderr, flush=True)


def _note(msg: str) -> None:
    print(f"  {_arrow()} {msg}", file=sys.stderr, flush=True)


def _warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr, flush=True)


def _fatal(msg: str, *, hint: str | None = None, code: int = EXIT_FAIL) -> int:
    print(f"[FATAL] {msg}", file=sys.stderr, flush=True)
    if hint:
        print(f"        {hint}", file=sys.stderr, flush=True)
    return code


# ---------------------------------------------------------------------------
# Spinner (stdlib only)
# ---------------------------------------------------------------------------

class Spinner:
    """Minimal ANSI spinner on a background thread. Falls back silently when
    stdout is not a tty (we emit line-per-event instead)."""

    def __init__(self, label: str = "") -> None:
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = label
        self._lock = threading.Lock()
        self._use_ansi = _is_tty()

    def update(self, status: str) -> None:
        with self._lock:
            self._status = status
        if not self._use_ansi:
            # Fall back: one line per status update, max ~1/sec.
            print(f"  {_arrow()} {status}", file=sys.stderr, flush=True)

    def _run(self) -> None:
        frames = cycle(SPINNER_UTF8 if _is_utf8() else SPINNER_ASCII)
        while not self._stop.is_set():
            with self._lock:
                status = self._status
            if self._use_ansi:
                # \r = carriage return, \x1b[K = clear to end of line
                sys.stderr.write(f"\r  {next(frames)} {status[:78]}\x1b[K")
                sys.stderr.flush()
            self._stop.wait(0.1)

    def __enter__(self) -> Spinner:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        if self._use_ansi:
            # Clear the spinner line before the next print.
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()


# ---------------------------------------------------------------------------
# Prereq detection: testable helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    name: str
    found: bool
    detail: str = ""
    install_cmd: str = ""
    blocking: bool = False  # True = fail fast; False = warn + continue


def install_hint_for_os(tool: str, os_name: str | None = None) -> str:
    """Return the install command for ``tool`` on the given OS, or "" if
    we don't have an opinion."""
    os_name = os_name or platform.system()
    if tool == "ffmpeg":
        if os_name == "Darwin":
            return "brew install ffmpeg"
        if os_name == "Linux":
            return "apt install ffmpeg  # or: dnf install ffmpeg"
        if os_name == "Windows":
            return "choco install ffmpeg  # or: winget install Gyan.FFmpeg"
    if tool == "python":
        if os_name == "Darwin":
            return "brew install python@3.13"
        if os_name == "Linux":
            return "apt install python3.13  # or use your distro's package manager"
        if os_name == "Windows":
            return "winget install Python.Python.3.13"
    return ""


def detect_python_ok(version: tuple[int, int, int] | None = None) -> bool:
    v = version or sys.version_info[:3]
    return v >= MIN_PYTHON


def detect_ffmpeg() -> Finding:
    path = shutil.which("ffmpeg")
    if path:
        return Finding(name="ffmpeg", found=True, detail=path)
    return Finding(
        name="ffmpeg",
        found=False,
        detail="not on PATH",
        install_cmd=install_hint_for_os("ffmpeg"),
        blocking=True,  # ffmpeg is required at runtime
    )


def detect_ytdlp() -> Finding:
    path = shutil.which("yt-dlp")
    if path:
        return Finding(name="yt-dlp", found=True, detail=path)
    return Finding(
        name="yt-dlp",
        found=False,
        detail="not on PATH, will install via pip in step 4",
        install_cmd="",
        blocking=False,
    )


def format_finding_row(f: Finding) -> str:
    mark = _check() if f.found else _cross()
    line = f"{mark} {f.name}"
    if f.detail:
        line += f" - {f.detail}"
    return line


# ---------------------------------------------------------------------------
# Venv path resolution
# ---------------------------------------------------------------------------

def resolve_venv_python(venv_path: Path, os_name: str | None = None) -> Path:
    """Return the Python interpreter inside a venv, handling Windows vs POSIX."""
    os_name = os_name or platform.system()
    if os_name == "Windows":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def resolve_venv_activate(venv_path: Path, os_name: str | None = None) -> Path:
    os_name = os_name or platform.system()
    if os_name == "Windows":
        return venv_path / "Scripts" / "Activate.ps1"
    return venv_path / "bin" / "activate"


# ---------------------------------------------------------------------------
# Pack selection
# ---------------------------------------------------------------------------

def parse_pack_choice(raw: str) -> str:
    """Accept '1'/'2'/'3' or 'lite'/'full'/'dev'. Raise ValueError otherwise."""
    s = (raw or "").strip().lower()
    numeric = {"1": "lite", "2": "full", "3": "dev"}
    if s in numeric:
        return numeric[s]
    if s in PACK_CHOICES:
        return s
    raise ValueError(f"invalid pack choice: {raw!r} (want 1/2/3 or lite/full/dev)")


# ---------------------------------------------------------------------------
# .env writing (atomic, preserves unrelated lines)
# ---------------------------------------------------------------------------

def write_env_file(path: Path, updates: dict[str, str]) -> None:
    """Write ``updates`` to ``path`` atomically.

    - Existing lines not in ``updates`` are preserved verbatim.
    - Keys in ``updates`` replace existing lines with the same key.
    - Never logs values.
    """
    existing: list[str] = []
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing = []

    replaced = set()
    out_lines: list[str] = []
    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            out_lines.append(f"{key}={updates[key]}")
            replaced.add(key)
        else:
            out_lines.append(line)

    for key, value in updates.items():
        if key not in replaced:
            out_lines.append(f"{key}={value}")

    # Defensive: reject values that would corrupt the .env line format.
    # `.strip()` in step_keys handles trailing whitespace on normal input;
    # this catches pasted multiline values or embedded NULs.
    _BAD_CHARS = ("\n", "\r", "\0")
    for key, value in updates.items():
        if any(bad in value for bad in _BAD_CHARS):
            raise ValueError(f"{key} contains control characters; refusing to write")

    content = "\n".join(out_lines).rstrip("\n") + "\n"

    # Atomic write via tempfile + rename
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=".env.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

@dataclass
class InstallerState:
    repo_root: Path
    args: argparse.Namespace
    venv_python: Path = field(default=Path(""))
    pack: str = "lite"
    findings: list[Finding] = field(default_factory=list)

    @property
    def non_interactive(self) -> bool:
        return bool(self.args.yes) or not _is_tty() or self.args.quiet


def step_prereq(state: InstallerState) -> int:
    _step(1, "Checking prerequisites")

    if not detect_python_ok():
        return _fatal(
            f"Python {sys.version_info.major}.{sys.version_info.minor} is too old, "
            f"need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+",
            hint=install_hint_for_os("python") or "Install a newer Python.",
            code=EXIT_ENV,
        )
    _ok(f"Python {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")

    findings = [detect_ffmpeg(), detect_ytdlp()]
    state.findings = findings
    blocking_missing = 0
    for f in findings:
        if f.found:
            _ok(format_finding_row(f))
        else:
            _bad(format_finding_row(f))
            if f.install_cmd:
                _note(f"install with: {f.install_cmd}")
            if f.blocking:
                blocking_missing += 1

    if blocking_missing > 0:
        if state.non_interactive:
            _warn(f"{blocking_missing} required tool(s) missing, continuing anyway "
                  "because --yes was set. Install them before running learn-video.")
        else:
            print("", file=sys.stderr)
            answer = input(
                f"  {blocking_missing} required tool(s) missing. Continue anyway? [y/N] "
            ).strip().lower()
            if answer != "y":
                _note("Install the missing tools above, then re-run this installer.")
                return EXIT_ENV
    return EXIT_OK


def step_venv(state: InstallerState) -> int:
    _step(2, "Virtualenv")

    if state.args.no_venv:
        state.venv_python = Path(sys.executable)
        _note("--no-venv: using current Python interpreter directly.")
        return EXIT_OK

    venv_path = (state.repo_root / (state.args.venv_path or ".venv")).resolve()

    if venv_path.exists() and any(venv_path.iterdir()):
        if state.non_interactive:
            _note(f"reusing existing venv at {venv_path}")
        else:
            answer = input(f"  Venv exists at {venv_path}. Reuse? [Y/n] ").strip().lower()
            if answer == "n":
                return _fatal(
                    "User declined existing venv reuse.",
                    hint="delete the .venv dir or pass --venv-path=<other>",
                    code=EXIT_CONFIG,
                )
    else:
        if not state.non_interactive:
            answer = input(f"  Create .venv at {venv_path}? [Y/n] ").strip().lower()
            if answer == "n":
                state.venv_python = Path(sys.executable)
                _note("skipping venv creation; will install into current Python.")
                return EXIT_OK
        with Spinner("creating venv"):
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except subprocess.CalledProcessError as exc:
                return _fatal(
                    f"venv creation failed: {exc.stderr.strip() if exc.stderr else exc}",
                    hint="check write permissions and disk space",
                    code=EXIT_FAIL,
                )
            except subprocess.TimeoutExpired:
                return _fatal("venv creation timed out after 180s", code=EXIT_FAIL)

    state.venv_python = resolve_venv_python(venv_path)
    if not state.venv_python.exists():
        return _fatal(
            f"venv python not found at {state.venv_python}",
            hint="the venv may be corrupt; delete and retry",
            code=EXIT_FAIL,
        )
    _ok(f"venv python: {state.venv_python}")
    return EXIT_OK


def step_pack(state: InstallerState) -> int:
    _step(3, "Feature pack")

    if state.args.pack:
        try:
            state.pack = parse_pack_choice(state.args.pack)
        except ValueError as exc:
            return _fatal(str(exc), code=EXIT_CONFIG)
        _note(f"using --pack={state.pack}")
        return EXIT_OK

    if state.non_interactive:
        return _fatal(
            "Non-interactive mode needs --pack={lite,full,dev}.",
            hint="pass --pack=lite (default), --pack=full, or --pack=dev",
            code=EXIT_CONFIG,
        )

    print("  Which provider stack do you want?", file=sys.stderr)
    print("    1) lite   Gemini only (~200 MB, default, covers --tier=lite/pro)", file=sys.stderr)
    print("    2) full   Gemini + Anthropic + Ollama (~350 MB, all tiers)", file=sys.stderr)
    print("    3) dev    full + pytest + coverage (for contributors)", file=sys.stderr)
    for _ in range(3):
        raw = input("  Choice [1]: ").strip() or "1"
        try:
            state.pack = parse_pack_choice(raw)
            _ok(f"selected: {state.pack}")
            return EXIT_OK
        except ValueError as exc:
            _bad(str(exc))
    return _fatal("too many invalid choices", code=EXIT_CONFIG)


def step_install(state: InstallerState) -> int:
    _step(4, "Installing packages")

    pip_upgrade_cmd = [
        str(state.venv_python), "-m", "pip", "install",
        "--upgrade", "pip",
    ]
    with Spinner("upgrading pip"):
        upgrade_proc = subprocess.run(
            pip_upgrade_cmd, capture_output=True, text=True, timeout=120,
        )
    if upgrade_proc.returncode != 0:
        _warn(f"pip upgrade exited {upgrade_proc.returncode}, continuing with existing pip. "
              "If the main install fails, upgrade pip manually and retry.")

    extras_spec = f".[{state.pack}]"
    pip_cmd = [str(state.venv_python), "-m", "pip", "install", extras_spec]

    # Outer deadline guards against hung subprocesses (network stall, etc.).
    INSTALL_TIMEOUT_S = 1800  # 30 minutes is plenty for a 350 MB install.
    start = time.monotonic()
    # Run pip with line-buffered output so we can drive the spinner.
    try:
        proc = subprocess.Popen(
            pip_cmd,
            cwd=state.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return _fatal(f"could not invoke pip: {exc}", code=EXIT_FAIL)

    tail: list[str] = []
    assert proc.stdout is not None
    with Spinner(f"pip install {extras_spec}") as spinner:
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            if len(tail) > 40:
                tail = tail[-40:]
            # Pull out meaningful actions for the spinner label.
            if line.startswith(("Collecting ", "Downloading ", "Building wheel")) or line.startswith("Successfully installed"):
                spinner.update(line[:76])
            if time.monotonic() - start > INSTALL_TIMEOUT_S:
                proc.kill()
                return _fatal(
                    f"pip install exceeded {INSTALL_TIMEOUT_S}s; aborting.",
                    hint="check network connectivity and retry",
                    code=EXIT_FAIL,
                )
        try:
            proc.wait(timeout=max(1, INSTALL_TIMEOUT_S - int(time.monotonic() - start)))
        except subprocess.TimeoutExpired:
            proc.kill()
            return _fatal("pip install timed out", code=EXIT_FAIL)
    elapsed = time.monotonic() - start

    if proc.returncode != 0:
        print("", file=sys.stderr)
        print("  Last pip output:", file=sys.stderr)
        for line in tail[-30:]:
            print(f"    {line}", file=sys.stderr)
        return _fatal(
            f"pip install failed with exit code {proc.returncode}",
            hint=f"re-run manually to debug: {' '.join(pip_cmd)}",
            code=EXIT_FAIL,
        )

    # Count installed packages from the final "Successfully installed" line.
    installed_count = 0
    for line in reversed(tail):
        if line.startswith("Successfully installed"):
            installed_count = len(line.split()[2:])
            break

    if installed_count:
        _ok(f"installed {installed_count} packages in {elapsed:.1f}s")
    else:
        _ok(f"pip exited clean in {elapsed:.1f}s (nothing new to install)")
    return EXIT_OK


_GEMINI_KEY_PATTERN = re.compile(r"^AIza[0-9A-Za-z_\-]{30,}$")
_ANTHROPIC_KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")


def _prompt_hidden(label: str) -> str:
    """getpass with a graceful fallback when no tty is available."""
    try:
        return getpass.getpass(f"  {label}: ")
    except OSError:
        # getpass raises OSError when there's no tty to read from.
        # GetPassWarning is emitted via warnings.warn (not raised), so we
        # don't catch it here; getpass already falls back internally.
        _warn("terminal doesn't support hidden input, key will be visible while typing")
        try:
            return input(f"  {label}: ")
        except EOFError:
            return ""


def step_keys(state: InstallerState) -> int:
    _step(5, "API keys")

    env_path = state.repo_root / ".env"
    updates: dict[str, str] = {}

    # GEMINI_API_KEY (required)
    gemini_key = state.args.gemini_key
    if not gemini_key and state.non_interactive:
        _warn("no --gemini-key provided and non-interactive, skipping .env write; "
              "you must set GEMINI_API_KEY before running learn-video")
    elif not gemini_key:
        print("  Get one at https://aistudio.google.com/apikey", file=sys.stderr)
        gemini_key = _prompt_hidden("Paste your GEMINI_API_KEY (input hidden)").strip()
        if gemini_key and not _GEMINI_KEY_PATTERN.match(gemini_key):
            _warn("key doesn't look like a Gemini key (expected prefix 'AIza…'); "
                  "saving anyway; learn-video will surface a real error if it's wrong")

    if gemini_key:
        updates["GEMINI_API_KEY"] = gemini_key
        _ok("will write GEMINI_API_KEY to .env")

    # ANTHROPIC_API_KEY (optional)
    anthropic_key = state.args.anthropic_key
    if not anthropic_key and not state.non_interactive:
        print("", file=sys.stderr)
        raw = _prompt_hidden("(optional) ANTHROPIC_API_KEY, only for --tier=max [skip]")
        raw = raw.strip()
        if raw:
            anthropic_key = raw
            if not _ANTHROPIC_KEY_PATTERN.match(raw):
                _warn("key doesn't look like an Anthropic key (expected 'sk-ant-…')")

    if anthropic_key:
        updates["ANTHROPIC_API_KEY"] = anthropic_key
        _ok("will write ANTHROPIC_API_KEY to .env")

    if not updates:
        _note("no keys provided, .env not modified")
        return EXIT_OK

    try:
        write_env_file(env_path, updates)
    except OSError as exc:
        return _fatal(f"could not write .env: {exc}", code=EXIT_FAIL)
    _ok(f"wrote {env_path}")
    return EXIT_OK


def step_smoke_test(state: InstallerState) -> int:
    _step(6, "Smoke test")
    if state.args.skip_smoke_test:
        _note("--skip-smoke-test: skipping import verification")
        return EXIT_OK

    checks: list[tuple[str, list[str]]] = [
        ("learn_video package",
         ["-c", "import learn_video; print(learn_video.__version__)"]),
        ("core deps",
         ["-c", "import pydantic, tenacity, json_repair"]),
    ]
    if state.pack in ("lite", "full", "dev"):
        checks.append((
            "langchain + langchain-google-genai",
            ["-c", "import langchain, langchain_core, langchain_google_genai"],
        ))
    if state.pack in ("full", "dev"):
        checks.append((
            "anthropic + ollama wrappers",
            ["-c", "import langchain_anthropic, langchain_ollama"],
        ))

    for label, argv in checks:
        with Spinner(label):
            try:
                proc = subprocess.run(
                    [str(state.venv_python), *argv],
                    cwd=state.repo_root,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                _bad(f"{label}: timed out")
                return EXIT_FAIL
        if proc.returncode != 0:
            _bad(f"{label}: failed")
            for line in (proc.stderr or "").splitlines()[-5:]:
                print(f"    {line}", file=sys.stderr)
            return _fatal(
                f"smoke test failed for: {label}",
                hint="re-run the installer with --pack=full if a provider wrapper is missing",
                code=EXIT_FAIL,
            )
        detail = (proc.stdout or "").strip() or "ok"
        _ok(f"{label}: {detail}")

    # Discover and run unit tests; unittest prints "Ran N tests" on both
    # success and failure so we also gate on returncode.
    with Spinner("running unit tests"):
        proc = subprocess.run(
            [str(state.venv_python), "-m", "unittest", "discover",
             "-s", "learn_video/tests", "-t", ".", "--locals"],
            cwd=state.repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
    match = re.search(r"Ran (\d+) tests? in", (proc.stderr or ""))
    count = match.group(1) if match else "?"
    if proc.returncode == 0:
        _ok(f"{count} unit tests passed")
    else:
        _bad(f"{count} unit tests ran; at least one failed")
        for line in (proc.stderr or "").splitlines()[-15:]:
            print(f"    {line}", file=sys.stderr)
        return _fatal(
            "unit tests failed during smoke check",
            hint="run manually to debug: python -m unittest discover -s learn_video/tests -t .",
            code=EXIT_FAIL,
        )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Final banner
# ---------------------------------------------------------------------------

def print_done(state: InstallerState) -> None:
    box = BOX_UTF8 if _is_utf8() else BOX_ASCII
    w = 65
    print("", file=sys.stderr)
    print(f"  {box['tl']}{box['h'] * (w - 2)}{box['tr']}", file=sys.stderr)
    print(f"  {box['v']}  Setup complete.{' ' * (w - 19)}{box['v']}", file=sys.stderr)
    print(f"  {box['bl']}{box['h'] * (w - 2)}{box['br']}", file=sys.stderr)
    print("", file=sys.stderr)

    print("  Try it:", file=sys.stderr)
    print(f'    {state.venv_python} -m learn_video.cli run "<url>"', file=sys.stderr)
    print("", file=sys.stderr)

    venv_dir = state.venv_python.parent.parent if state.venv_python.name.lower().startswith("python") else None
    if venv_dir and not state.args.no_venv:
        print("  Activate the venv in new shells:", file=sys.stderr)
        if platform.system() == "Windows":
            print(f"    .\\{venv_dir.name}\\Scripts\\Activate.ps1   # PowerShell", file=sys.stderr)
            print(f"    source {venv_dir.name}/bin/activate    # git-bash / WSL", file=sys.stderr)
        else:
            print(f"    source {venv_dir.name}/bin/activate    # macOS / Linux", file=sys.stderr)
            print(f"    .\\{venv_dir.name}\\Scripts\\Activate.ps1   # Windows PowerShell", file=sys.stderr)
        print("", file=sys.stderr)

    print("  Install as a Claude Code skill (any agent):", file=sys.stderr)
    print("    npx skills add 9Tech-Solutions/learn-video", file=sys.stderr)
    print("", file=sys.stderr)


# ---------------------------------------------------------------------------
# Argparse + main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install.py",
        description="Cross-platform interactive installer for learn-video.",
    )
    p.add_argument("--yes", "-y", action="store_true",
                   help="skip interactive prompts where possible (use defaults / flags)")
    p.add_argument("--pack", choices=PACK_CHOICES, default=None,
                   help="feature pack to install (default asks interactively)")
    p.add_argument("--no-venv", action="store_true",
                   help="install into the current Python instead of creating a venv")
    p.add_argument("--venv-path", default=None,
                   help="venv directory (default: .venv in repo root)")
    p.add_argument("--gemini-key", default=None,
                   help="GEMINI_API_KEY value (else prompted interactively)")
    p.add_argument("--anthropic-key", default=None,
                   help="ANTHROPIC_API_KEY value (optional, only for --tier=max)")
    p.add_argument("--skip-smoke-test", action="store_true",
                   help="skip the post-install import/test-discovery verification")
    p.add_argument("--quiet", action="store_true",
                   help="minimize prompts (implies --yes where possible)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    state = InstallerState(repo_root=repo_root, args=args)

    box = BOX_UTF8 if _is_utf8() else BOX_ASCII
    w = 65
    title = "learn-video installer"
    subtitle = "Set up in about 2 minutes."
    print(f"\n  {box['tl']}{box['h'] * (w - 2)}{box['tr']}", file=sys.stderr)
    print(f"  {box['v']}  {title.ljust(w - 6)}{box['v']}", file=sys.stderr)
    print(f"  {box['v']}  {subtitle.ljust(w - 6)}{box['v']}", file=sys.stderr)
    print(f"  {box['bl']}{box['h'] * (w - 2)}{box['br']}", file=sys.stderr)

    steps = (
        step_prereq,
        step_venv,
        step_pack,
        step_install,
        step_keys,
        step_smoke_test,
    )
    for step in steps:
        rc = step(state)
        if rc != EXIT_OK:
            return rc

    print_done(state)
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        sys.exit(130)
