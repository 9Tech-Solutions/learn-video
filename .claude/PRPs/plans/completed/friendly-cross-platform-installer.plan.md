# Plan: Friendly Cross-Platform Installer

## Summary

Replace the bash-only `setup.sh` with a single cross-platform Python installer (`scripts/install.py`) driven by thin shims for each OS. Add interactive feature-pack selection (lite/full/dev), API-key prompt with hidden input, prerequisite detection with actionable install commands per OS, a live progress spinner during `pip install`, and a post-install smoke test. Result: one codepath that works on Windows PowerShell, Windows git-bash, macOS zsh, and Linux bash — with visibly better UX than the current "350MB install with a wall of text" experience.

## User Story

As a developer cloning `learn-video` for the first time,
I want a single command that detects my OS, offers the right install flavor, collects my API key interactively, and tells me whether it actually works,
So that I can go from `git clone` to a successful first extraction in under two minutes without reading docs or guessing at PATH issues.

## Problem → Solution

**Current:**
```
$ ./setup.sh
→ Only runs in bash. Windows PowerShell users can't.
→ Always installs the full 350MB stack, even if you only want Gemini.
→ Prints a wall of text at the end; no verification that anything works.
→ User must then manually: cp .env.example .env, edit, export, etc.
```

**Desired:**
```
$ python scripts/install.py   (or ./setup.sh / .\setup.ps1 — all delegate)
[1/6] Checking prerequisites  ✓ Python 3.13.5  ✓ ffmpeg  ✗ yt-dlp (will install)
[2/6] Virtualenv              Create .venv here? [Y/n]
[3/6] Feature pack            1) lite 2) full 3) dev   Choice [1]: _
[4/6] Installing packages     ⠋ langgraph... (spinner + elapsed)
[5/6] API keys                Paste GEMINI_API_KEY (hidden): _
[6/6] Smoke test              ✓ learn_video 0.1.0 imports cleanly
Try it:   python -m learn_video.cli run "<url>"
```

## Metadata

- **Complexity**: Medium
- **Source PRD**: N/A (free-form; follows up on the README/repo-improvement discussion)
- **PRD Phase**: N/A
- **Estimated Files**: 7 (1 new installer, 1 new PowerShell shim, 1 rewrite `setup.sh`, `pyproject.toml` deps split, README section rewrite, new test module, CHANGELOG entry)

---

## UX Design

### Before

```
$ ./setup.sh
==> Python: Python 3.13.5
WARN: ffmpeg not found on PATH. Install it before running learn-video:
       macOS:   brew install ffmpeg
       Linux:   apt install ffmpeg
       Windows: choco install ffmpeg
==> Creating virtualenv at .venv/
==> Upgrading pip
==> Installing requirements (this pulls ~350 MB: ...)
[... 30-60s of raw pip output ...]
==============================================================
Setup complete.
Next steps:
  1. Copy .env.example to .env and set GEMINI_API_KEY
       cp .env.example .env && $EDITOR .env
  2. Activate the venv in new shells:
       source .venv/bin/activate
  3. Try it:
       python -m learn_video.cli run "..."
  4. (optional) Install as a Claude Code skill:
       cp commands/learn-video.md ~/.claude/commands/
       cp -r learn_video ~/.claude/scripts/
==============================================================
```

Problems: bash-only, full 350MB always, no .env interaction, no smoke test, no progress feedback during pip install.

### After

```
$ python scripts/install.py      # or ./setup.sh, or .\setup.ps1
┌─────────────────────────────────────────────────────────────┐
│  learn-video installer                                      │
│  Set up in about 2 minutes.                                 │
└─────────────────────────────────────────────────────────────┘

[1/6] Checking prerequisites
  ✓ Python 3.13.5 (>= 3.11 required)
  ✓ ffmpeg 7.1.1 at /usr/bin/ffmpeg
  ✗ yt-dlp not found — will install via pip in step 4
  → 1 missing; nothing to do now, continuing.

[2/6] Virtualenv
  Create .venv in this directory? [Y/n] _
  ⠋ Creating venv...
  ✓ Activated .venv/bin/activate

[3/6] Feature pack
  Which provider stack do you want?
    1) lite   — Gemini only (~200 MB, recommended for default --tier=lite/pro)
    2) full   — Gemini + Anthropic + Ollama (~350 MB, all tiers)
    3) dev    — full + pytest + coverage (for contributing)
  Choice [1]: _

[4/6] Installing packages
  ⠋ pip install .[lite] ...
  ⠙ Downloading langgraph 1.1.2 ...
  ⠹ Building wheel for faster-whisper ...
  ✓ Installed 23 packages in 52s

[5/6] API keys
  GEMINI_API_KEY is required. Get one at https://aistudio.google.com/apikey
  Paste your GEMINI_API_KEY (input hidden): _
  ✓ Wrote GEMINI_API_KEY to .env

  ANTHROPIC_API_KEY? (optional, only for --tier=max) [skip]: _
  → Skipped.

[6/6] Smoke test
  ⠋ Importing learn_video ...
  ✓ learn_video 0.1.0
  ✓ pydantic 2.9.x, tenacity 9.x, langchain 1.2.x
  ✓ 74 unit tests discovered (run them with: python -m unittest discover -s learn_video/tests -t .)

┌─────────────────────────────────────────────────────────────┐
│  Setup complete.                                            │
└─────────────────────────────────────────────────────────────┘

Try it:
  python -m learn_video.cli run "https://youtu.be/<id>"

Activate the venv in new shells:
  source .venv/bin/activate        # macOS/Linux/git-bash
  .\.venv\Scripts\Activate.ps1     # Windows PowerShell

Install as a Claude Code skill:
  npx skills add 9Tech-Solutions/learn-video
```

### Interaction Changes

| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Invocation | `./setup.sh` (bash only) | `python scripts/install.py` (any OS); `./setup.sh` and `.\setup.ps1` delegate | Shims preserve README muscle memory |
| Feature pack | Hardcoded full install | User picks lite/full/dev (default lite) | Uses `[project.optional-dependencies]` groups |
| Progress feedback | Raw pip output stream | Unicode spinner with current action | Stdlib only — no `rich` dep |
| API key | User manually copies `.env.example` and edits | Hidden-input prompt, writes `.env` | Uses `getpass.getpass()` |
| Verification | None | Import smoke test + version echo | Caught package mismatches before first run |
| ffmpeg missing | Warn only, continue | Warn + show exact install command for detected OS | `platform.system()` branches |
| Non-interactive mode | N/A | `--yes --pack=lite --gemini-key=$GEMINI_API_KEY` flags | For CI / Dockerfile use |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `learn_video/ffmpeg_util.py` | 1-24 | Canonical `shutil.which` + `EnvironmentError_` pattern to mirror for prereq detection |
| P0 | `learn_video/errors.py` | 1-40 | Four-class error taxonomy; installer uses `ConfigurationError` / `EnvironmentError_` the same way |
| P0 | `learn_video/cli.py` | 39-80 | Argparse style, `_parser()` factory pattern, exit-code semantics |
| P0 | `pyproject.toml` | 25-45 | Current deps + existing `[project.optional-dependencies]` block (only `dev` now — will add `lite` and `full`) |
| P0 | `setup.sh` | 1-69 | What's being replaced; preserve the "cd to REPO_ROOT then do stuff" invariant |
| P1 | `learn_video/ingest.py` | 18-28 | `_require_ytdlp()` — second example of the prereq pattern, useful reference |
| P1 | `learn_video/logging_.py` | 1-59 | Stderr formatter style — installer's output should feel like the same tool |
| P2 | `learn_video/tests/test_ingest_format.py` | all | Example of a pure-function test with no fixtures, useful template for installer helpers |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| Python `venv` on Windows path layout | [docs.python.org/3/library/venv.html](https://docs.python.org/3/library/venv.html) | Activation script lives at `.venv/Scripts/Activate.ps1` (PowerShell), `.venv/Scripts/activate.bat` (cmd.exe), or `.venv/Scripts/activate` (git-bash) on Windows; `.venv/bin/activate` elsewhere |
| `getpass.getpass()` behavior | [docs.python.org/3/library/getpass.html](https://docs.python.org/3/library/getpass.html) | Prints prompt to stderr, reads from tty — fallbacks to plain input() if no tty (warns user); works across OS |
| pip programmatic install | [pip.pypa.io/en/stable/user_guide/](https://pip.pypa.io/en/stable/user_guide/) | Invoke via subprocess, NOT the `pip` Python module (officially unsupported) — use `[sys.executable, "-m", "pip", "install", ...]` |
| `[project.optional-dependencies]` syntax | [packaging.python.org/en/latest/specifications/pyproject-toml/](https://packaging.python.org/en/latest/specifications/pyproject-toml/) | Install via `pip install .[groupname]` or `.[group1,group2]`; groups can reference each other |
| Windows PowerShell execution policy | Microsoft docs | `.ps1` scripts may be blocked by default; the shim should handle RemoteSigned/Restricted gracefully or print the unblock command |

**KEY_INSIGHT**: `python -m pip install` (via subprocess) is the official way to programmatically install packages. Never `import pip; pip.main(...)` — that's unsupported and breaks across versions.
**APPLIES_TO**: Step 4 (package install) in `scripts/install.py`.
**GOTCHA**: On Windows in some environments, `sys.executable` points at the base Python, not the venv's Python. After creating the venv, resolve the venv's python explicitly (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` elsewhere).

---

## Patterns to Mirror

### PREREQ_DETECTION
```python
# SOURCE: learn_video/ffmpeg_util.py:10-16
def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise EnvironmentError_(
            "ffmpeg not found on PATH",
            install_cmd="choco install ffmpeg  # or apt install ffmpeg",
        )
    return path
```

Installer's prereq-check step reuses this exact shape but doesn't raise — it returns `(found: bool, path: str|None, install_cmd: str)` so the UI can show a ✓/✗ table.

### ERROR_TAXONOMY
```python
# SOURCE: learn_video/errors.py:14-36
class TransientError(LearnVideoError): ...

class ConfigurationError(LearnVideoError):
    def __init__(self, message: str, fix_hint: str | None = None) -> None:
        super().__init__(message)
        self.fix_hint = fix_hint

class EnvironmentError_(LearnVideoError):
    def __init__(self, message: str, install_cmd: str | None = None) -> None:
        super().__init__(message)
        self.install_cmd = install_cmd
```

Installer raises `ConfigurationError` on bad user input (invalid feature-pack choice), `EnvironmentError_` when Python itself is wrong version. Exits with the same exit codes as the main CLI (2 for config, 3 for env).

### SUBPROCESS_INVOCATION
```python
# SOURCE: learn_video/ingest.py:31-45
proc = subprocess.run(
    [ytdlp, "--dump-json", "--no-warnings", "--skip-download", url],
    check=True,
    capture_output=True,
    text=True,
    timeout=120,
)
```

Installer invokes `pip install` via subprocess the same way, but with `stdout=subprocess.PIPE` + a background thread that reads lines so we can drive the spinner. Never uses `check=True` during install (we want to display the error pretty, not let subprocess raise CalledProcessError).

### LOGGING_STYLE
```python
# SOURCE: learn_video/logging_.py:24-31
def emit(stage: str, message: str) -> None:
    idx = STAGES.index(stage.upper())
    prefix = f"[{idx + 1}/{len(STAGES)} {stage.upper()}]" if idx >= 0 else f"[{stage}]"
    print(f"{prefix} {message}", file=sys.stderr, flush=True)
```

Installer uses `[N/6 STEP]` on stderr matching the main CLI's stage-line look. Unicode check/cross marks (✓/✗/→) match the visual vocabulary. Never emits to stdout (stdout is reserved for machine-readable output if we later add `--json`).

### ARGPARSE_PATTERN
```python
# SOURCE: learn_video/cli.py:39-78
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="learn-video", description="...")
    sub = p.add_subparsers(dest="cmd")
    run_p = sub.add_parser("run", help="...")
    run_p.add_argument("--tier", choices=("lite", "pro", "max"), default=None)
```

Installer has flags: `--yes`, `--pack={lite,full,dev}`, `--no-venv`, `--gemini-key=...`, `--anthropic-key=...`, `--skip-smoke-test`. All optional; without any, full interactive flow runs.

### TEST_STRUCTURE
```python
# SOURCE: learn_video/tests/test_ingest_format.py:5-15
class TestFormatForDuration(unittest.TestCase):
    def test_short_video_gets_720p(self):
        self.assertIn("720", _format_for_duration(600.0))
```

Installer-helper tests follow the same pattern: unittest.TestCase, no fixtures, pure functions. Interactive parts are tested by mocking `input` / `getpass.getpass` / `subprocess.run`.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `scripts/install.py` | CREATE | The cross-platform installer itself. ~350-450 lines. |
| `scripts/__init__.py` | CREATE | Empty, so `scripts/` is a real package (makes imports from test files work). |
| `setup.sh` | UPDATE (rewrite to shim) | ~15 lines. Just finds Python and delegates: `exec "$PYTHON_BIN" "$REPO_ROOT/scripts/install.py" "$@"`. |
| `setup.ps1` | CREATE | PowerShell equivalent of setup.sh shim. ~20 lines. |
| `pyproject.toml` | UPDATE | Split `dependencies` into a smaller base + `[project.optional-dependencies]` groups: `lite`, `full`, `dev`. Keep `dev` as-is but add pytest/coverage only; move provider SDKs into the groups. |
| `requirements.txt` | UPDATE (deprecate with comment) | Keep as `pip install -r requirements.txt` shortcut for `pip install .[full]`. Add header comment pointing users at the installer or extras syntax. |
| `learn_video/tests/test_installer.py` | CREATE | Unit tests for installer's pure helpers (prereq detection, pack resolution, env-writing, venv-path resolution). Mock subprocess + input + getpass. ~15 tests. |
| `README.md` | UPDATE | Quickstart section: lead with `python scripts/install.py` (or `./setup.sh`). Show the interactive prompts. Move the manual-install path to a "Manual install" subsection for contributors. |
| `CHANGELOG.md` | UPDATE | Append 0.2.0 (or 0.1.1) entry describing installer rewrite. |
| `.github/workflows/tests.yml` | UPDATE | Add a non-interactive installer smoke test as a new job (`python scripts/install.py --yes --pack=dev --skip-smoke-test` followed by running the unit suite). Proves the installer stays working across OS × Python. |

## NOT Building

- **Not** adding a `learn-video demo` subcommand (separate plan — would follow this one).
- **Not** publishing to PyPI (tracked as improvement #3 in the roadmap; requires repo-scope decisions about release automation).
- **Not** adding a `rich` / `textual` / `tqdm` dependency to the installer. Stdlib only — spinner implemented with a small thread + ANSI codes.
- **Not** auto-installing system packages (brew/apt/choco) on the user's behalf. We detect and show the command; user runs it. Automatic system-package installs are a support-nightmare (admin prompts, package-manager differences, permission errors).
- **Not** writing a `learn_video.install` module inside the package. The installer lives at `scripts/install.py` at repo root, because it must run before the package is installed.
- **Not** replacing `requirements.txt` entirely — keeping it as a shortcut for CI and for users who just want `pip install -r`.
- **Not** changing the runtime pipeline or any stage code. Pure packaging/UX work.

---

## Step-by-Step Tasks

### Task 1: Split pyproject.toml deps into optional-dependency groups
- **ACTION**: Move provider SDKs out of top-level `dependencies`; define `lite` / `full` / `dev` groups.
- **IMPLEMENT**:
  - Top-level `dependencies` keeps only: `pydantic`, `tenacity`, `json-repair`, `python-dotenv`, `tomli; python_version < '3.11'`.
  - Add to `[project.optional-dependencies]`:
    - `lite = ["yt-dlp>=2026.1.0", "faster-whisper>=1.2.0", "langgraph>=1.1.0,<2.0", "langchain>=1.2.0,<2.0", "langchain-core>=1.0.0,<2.0", "langchain-google-genai>=4.2.0,<5.0"]`
    - `full = ["learn-video[lite]", "langchain-anthropic>=1.4.0,<2.0", "langchain-ollama>=1.1.0,<2.0"]`
    - `dev = ["learn-video[full]", "pytest>=8.0", "pytest-cov>=5.0"]`
- **MIRROR**: `pyproject.toml:41-45` for the `[project.optional-dependencies]` format (already has `dev` key).
- **IMPORTS**: N/A (TOML edit).
- **GOTCHA**: Referencing `learn-video[lite]` inside `full` requires pip ≥ 21.2 (inline self-reference); the workflow already uses `pip` ≥ 23 so fine. Confirm with `pip install --dry-run .[full]` after the change.
- **VALIDATE**: `pip install --dry-run .[lite]` resolves; `pip install --dry-run .[full]` resolves and is a strict superset.

### Task 2: Create `scripts/install.py` skeleton + argparse
- **ACTION**: Create the installer module with its CLI surface but no logic yet — just the parser, main, and section placeholders.
- **IMPLEMENT**: `main(argv=None) -> int`. Parser supports `--yes`, `--pack={lite,full,dev}`, `--no-venv`, `--gemini-key=...`, `--anthropic-key=...`, `--skip-smoke-test`, `--venv-path=PATH`, `--quiet`. Each phase is a function: `step_prereq()`, `step_venv()`, `step_pack()`, `step_install()`, `step_keys()`, `step_smoke_test()`, `print_done()`.
- **MIRROR**: `learn_video/cli.py:39-78` for argparse structure + factory pattern. Exit codes: 0 success, 2 config, 3 env.
- **IMPORTS**: `argparse`, `sys`, `os`, `platform`, `shutil`, `subprocess`, `getpass`, `pathlib.Path`, `time`, `threading`.
- **GOTCHA**: The installer cannot `from learn_video.errors import ...` — it may run before install. Duplicate the two exception classes it needs (`ConfigurationError`, `EnvironmentError_`) inline or don't use them (simpler: plain sys.exit with clear stderr message).
- **VALIDATE**: `python scripts/install.py --help` prints usage. `python scripts/install.py --yes --pack=lite --no-venv --skip-smoke-test` runs through all placeholders without errors.

### Task 3: Implement `step_prereq()` — detect Python, ffmpeg, yt-dlp
- **ACTION**: Check each required tool; return a list of findings to display as a ✓/✗ table.
- **IMPLEMENT**:
  - Python check: `sys.version_info >= (3, 11)` else fail with exit 3 + "install Python 3.11+".
  - ffmpeg: `shutil.which("ffmpeg")`; if missing, classify missing with OS-specific install hint (`platform.system()` → "Darwin" → `brew install ffmpeg`, "Linux" → `apt install ffmpeg` or `dnf install ffmpeg`, "Windows" → `choco install ffmpeg` or `winget install Gyan.FFmpeg`).
  - yt-dlp: `shutil.which("yt-dlp")`; if missing, note "will be installed via pip in step 4" — not a hard blocker.
  - faster-whisper: check lazily — binary ships with the package.
- **MIRROR**: `learn_video/ffmpeg_util.py:10-16` for the `shutil.which` pattern. Don't raise — return a dataclass `Finding(name, found, path, install_cmd)`.
- **IMPORTS**: `shutil`, `platform`, `sys`.
- **GOTCHA**: On Windows git-bash, `ffmpeg` may live at `/c/work/tools/ffmpeg/bin/ffmpeg` (forward slashes). `shutil.which` handles this. Don't hardcode slashes in printed paths.
- **VALIDATE**: On a machine without ffmpeg, output shows `✗ ffmpeg not found — install with: brew install ffmpeg` and continues (doesn't hard-fail). On a machine without Python 3.11+, exits 3 with the right hint.

### Task 4: Implement `step_venv()` — create + prep virtualenv
- **ACTION**: Offer to create a `.venv` in the repo root (skippable via `--no-venv` or user declining).
- **IMPLEMENT**:
  - Resolve target: `Path(args.venv_path or ".venv").resolve()`.
  - If already exists and non-empty → ask "use existing? [Y/n]".
  - Else: `subprocess.run([sys.executable, "-m", "venv", str(target)], check=False)`.
  - Compute venv python: `target / ("Scripts/python.exe" if platform.system()=="Windows" else "bin/python")`. Store in module-level var for downstream subprocess calls.
  - Compute activate hint for the final banner (both Windows and POSIX forms).
- **MIRROR**: None — this is new pattern. But use `subprocess.run` the same way as `ingest.py:31-45`.
- **IMPORTS**: `pathlib.Path`, `subprocess`, `sys`, `platform`.
- **GOTCHA**: After creating a venv, `sys.executable` still points to the parent Python. All further `pip install` invocations MUST use the venv's python, not `sys.executable`.
- **VALIDATE**: After this step, `venv_python.exists()` is true; `venv_python -m pip --version` returns a pip version.

### Task 5: Implement `step_pack()` — interactive feature-pack selection
- **ACTION**: Numbered menu asking which extras group to install. Default = 1 (lite).
- **IMPLEMENT**:
  - If `args.pack` set via CLI, skip the prompt.
  - Else: print 3-option menu with descriptions; `input("Choice [1]: ")`. Accept 1/2/3 or lite/full/dev. Re-ask on bad input (max 3 retries then fail).
  - Return normalised `pack_name: str`.
- **MIRROR**: None. Simple stdlib `input()`. Don't use the `[N/6 STEP]` emit for the prompt itself — only for the status line before/after.
- **IMPORTS**: `sys` (for stdin detection — if not a tty, require `--pack` flag).
- **GOTCHA**: `input()` raises `EOFError` when stdin is redirected (CI). Detect with `sys.stdin.isatty()` and require `--pack` + `--yes` when non-interactive.
- **VALIDATE**: Interactive: user enters `2` → pack_name = "full". Non-interactive without `--pack`: exits with helpful error. `--pack=dev`: returns "dev" without prompting.

### Task 6: Implement `step_install()` — pip install with spinner
- **ACTION**: Run `venv_python -m pip install ".[pack_name]"` with live spinner and status updates.
- **IMPLEMENT**:
  - Start subprocess with `stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True`.
  - Spin a background thread that reads lines as they arrive; parse for package names to display ("Downloading X", "Building wheel for Y"). Keep last line visible on the current terminal row (ANSI `\r` + clear-to-end-of-line).
  - Spinner frames: `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` rotated every 100ms. Fall back to ASCII `|/-\` if stdout is not a tty.
  - Show elapsed time in the final "done (52.3s)" line.
  - If pip exits non-zero: show last 30 lines of output and exit 3.
- **MIRROR**: `learn_video/logging_.py:34-44` for the `stage()` context-manager elapsed-time pattern.
- **IMPORTS**: `subprocess`, `threading`, `time`, `itertools`, `sys`.
- **GOTCHA**: Windows terminal: the ANSI `\r` + clear trick works in modern Windows Terminal but not in ancient cmd.exe. Detect with `sys.stdout.isatty()` — if false, fall back to one-line-per-second status updates.
- **VALIDATE**: On an interactive terminal: spinner visible, single status line, final "✓ Installed N packages in Ns". On CI (piped stdout): line-per-status, no ANSI codes. pip failure: last 30 lines printed, exit 3.

### Task 7: Implement `step_keys()` — collect API keys and write `.env`
- **ACTION**: Prompt for `GEMINI_API_KEY` (required) and `ANTHROPIC_API_KEY` (optional) using hidden input. Write a `.env` file if user provides keys.
- **IMPLEMENT**:
  - If `args.gemini_key` set, use it; else `getpass.getpass("Paste your GEMINI_API_KEY (input hidden): ")`.
  - If existing `.env` already sets `GEMINI_API_KEY`, offer to keep/overwrite.
  - Basic validation: Gemini keys start with `AIza` (≥35 chars); warn (don't reject) if the pasted key doesn't match pattern.
  - Write `.env` atomically: write to `.env.tmp`, then rename. Preserve any existing non-key lines the user may have added.
  - Same flow for anthropic; default is skip.
  - Never log the key value — only confirm "✓ Wrote GEMINI_API_KEY to .env".
- **MIRROR**: None directly. `learn_video/cli.py:27-36` shows the existing dotenv-load pattern — installer writes the file that pattern reads.
- **IMPORTS**: `getpass`, `pathlib.Path`, `tempfile`.
- **GOTCHA**: `getpass.getpass()` on some git-bash setups prints the input instead of hiding it (terminal emulator issue). Detect by reading from `/dev/tty` first; if that fails, warn and fall back to `input()` with a clear "⚠ terminal doesn't support hidden input — key will be visible while typing".
- **VALIDATE**: Provide `--gemini-key=test-AIza-xxx` non-interactively → `.env` contains `GEMINI_API_KEY=test-AIza-xxx` and nothing else sensitive. Interactive path: prompt hides input (or warns). Re-run preserves unrelated lines in .env.

### Task 8: Implement `step_smoke_test()` — import check + test discovery
- **ACTION**: Verify the install actually works.
- **IMPLEMENT**:
  - Run `venv_python -c "import learn_video; print(learn_video.__version__)"`. Assert output matches `0.x.y`.
  - Run `venv_python -c "import pydantic, tenacity, json_repair; import langchain_google_genai"` (always) and provider-specific imports only if the pack includes them.
  - Run `venv_python -m unittest discover -s learn_video/tests -t . --locals` and count tests (don't fail on test failures — just report "N tests discovered; pending first run").
  - Each check shown as `⠋ ... → ✓` or `✗` with the error.
- **MIRROR**: `learn_video/tests/test_ingest_format.py` — structure your smoke-test-helper the same way (pure function returning `list[dict]`).
- **IMPORTS**: `subprocess`, `re`.
- **GOTCHA**: Running `unittest discover` from a fresh install directory can fail if PYTHONPATH isn't set. Cd to repo root before invoking; venv's python already has repo on path via editable install from step 6.
- **VALIDATE**: On a clean install: all ✓, reports `74 tests discovered`. If a required dep missing: shows which import failed and suggests `python scripts/install.py --pack=full`.

### Task 9: Implement `print_done()` — final next-steps banner
- **ACTION**: Print activation hints (OS-correct) and the three most useful next commands.
- **IMPLEMENT**:
  - Unicode box frame (ASCII fallback if no utf-8).
  - Activation line: show both `source .venv/bin/activate` and `.\.venv\Scripts\Activate.ps1`, with the OS-correct one highlighted first.
  - Next commands: `python -m learn_video.cli run "<url>"`, `npx skills add 9Tech-Solutions/learn-video`, `python -m learn_video.cli --help`.
  - Link to README for more flags.
- **MIRROR**: Existing `setup.sh:51-68` for what to print, but formatted better.
- **IMPORTS**: `platform`, `sys`.
- **GOTCHA**: On Windows cmd.exe, box-drawing characters can render as mojibake. Detect via `sys.stdout.encoding` — if it's not utf-8, fall back to ASCII `+--+` frames.
- **VALIDATE**: On macOS: POSIX activation line first. On Windows PowerShell: PowerShell activation first. Running the shown CLI command works.

### Task 10: Rewrite `setup.sh` as a thin shim
- **ACTION**: Replace current 69-line bash script with a ~20-line delegator.
- **IMPLEMENT**:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python"
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
      echo "ERROR: Python 3.11+ not found. Install it and retry." >&2
      exit 1
  fi
  exec "$PYTHON_BIN" "$REPO_ROOT/scripts/install.py" "$@"
  ```
- **MIRROR**: Preserve existing `setup.sh:5-18` Python-detection block (lines 5-18 of the current file).
- **IMPORTS**: N/A (bash).
- **GOTCHA**: `exec` replaces the shell process — stdin/stdout/stderr pass through. Without `exec`, signal handling (Ctrl+C) gets weird.
- **VALIDATE**: `./setup.sh --help` shows the Python installer's help. `./setup.sh --yes --pack=lite --skip-smoke-test` runs the installer non-interactively.

### Task 11: Create `setup.ps1` PowerShell shim
- **ACTION**: PowerShell equivalent of setup.sh.
- **IMPLEMENT**:
  ```powershell
  #!/usr/bin/env pwsh
  # learn-video installer shim (PowerShell).
  $ErrorActionPreference = "Stop"
  $RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
  $Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
  try {
      & $Python --version | Out-Null
  } catch {
      Write-Error "Python 3.11+ not found. Install it and retry."
      exit 1
  }
  & $Python "$RepoRoot/scripts/install.py" @args
  exit $LASTEXITCODE
  ```
- **MIRROR**: Same logic as `setup.sh` translated to PowerShell.
- **IMPORTS**: N/A (PowerShell).
- **GOTCHA**: PowerShell execution policy may block unsigned `.ps1`. README must mention `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` as a one-liner for users who hit this. Don't try to change policy in the script itself.
- **VALIDATE**: `.\setup.ps1 --help` on Windows PowerShell 7+ shows installer help. On Windows PowerShell 5.1 (older), works too if policy allows.

### Task 12: Write unit tests in `learn_video/tests/test_installer.py`
- **ACTION**: Cover the pure functions (not the interactive loop).
- **IMPLEMENT**: Tests for (at minimum):
  - `detect_python_ok()` — version gate (mock `sys.version_info`).
  - `detect_ffmpeg()` — present / absent (mock `shutil.which`).
  - `install_hint_for_os()` — "Darwin"→brew, "Linux"→apt, "Windows"→choco, "Other"→empty.
  - `resolve_venv_python()` — Windows path vs POSIX path.
  - `write_env_file()` — creates `.env`, preserves existing lines, atomic via `.tmp`+rename.
  - `parse_pack_choice()` — "1"/"lite"→"lite", "2"/"full"→"full", invalid→raises.
  - `format_finding_row()` — Unicode ✓/✗ in tty mode, ASCII fallback otherwise.
  - Mocked `step_install` happy path: subprocess returns 0 → function returns True.
  - Mocked `step_install` pip failure: subprocess returns 1 → function returns False with captured tail.
- **MIRROR**: `learn_video/tests/test_ingest_format.py` for style. No fixtures; `unittest.TestCase`; plain `assert*` methods.
- **IMPORTS**: `unittest`, `unittest.mock`, `tempfile`, `pathlib`. Add the scripts/ dir to `sys.path` in the test file's setUp so it can import install.py.
- **GOTCHA**: `scripts/install.py` isn't part of the `learn_video` package. Tests need `sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))` before `import install`. Or keep the testable helpers in a small module that can be imported from tests, e.g. `scripts/_install_helpers.py`.
- **VALIDATE**: All new tests pass locally. Total test count grows to 85+ (74 existing + ~12 new).

### Task 13: Update CI workflow to exercise the installer
- **ACTION**: Add a job that runs `python scripts/install.py` non-interactively on each matrix cell.
- **IMPLEMENT**: Append a new step before "Run unit tests" in `.github/workflows/tests.yml`:
  ```yaml
  - name: Installer smoke test (non-interactive)
    run: |
      python scripts/install.py --yes --pack=dev --no-venv --skip-smoke-test \
        --gemini-key=dummy-ci-key-AIza-placeholder
  ```
  (`--no-venv` so CI reuses actions/setup-python; `--skip-smoke-test` so we don't double up on test discovery; dummy key to satisfy the flow without hitting any API.)
- **MIRROR**: `.github/workflows/tests.yml` existing step pattern (every step has `name` + `run`/`uses`).
- **IMPORTS**: N/A (YAML).
- **GOTCHA**: The installer will want to write `.env` in the repo dir. Make sure CI doesn't fail on `.env` being present afterwards (it's in `.gitignore` already). The dummy key must not look like a real one — use "dummy-ci-key-AIza-placeholder".
- **VALIDATE**: CI run after merge is green on all 6 matrix cells. Time-cost delta: each job +~5s (installer runs fast because no actual pip install happens — `dev` extras reinstalls an already-satisfied set).

### Task 14: Update README Quickstart section
- **ACTION**: Rewrite the Quickstart to lead with the new installer.
- **IMPLEMENT**:
  - Replace the current "1. Clone and install / 2. Provide API keys / 3. Run / 4. Install as a Claude Code skill" with:
    1. One-liner: `npx skills add 9Tech-Solutions/learn-video` (existing)
    2. Full install (recommended for CLI users):
       ```bash
       git clone https://github.com/9Tech-Solutions/learn-video
       cd learn-video
       ./setup.sh            # macOS/Linux/git-bash
       .\setup.ps1           # Windows PowerShell
       # OR: python scripts/install.py   (any OS)
       ```
    3. Show a short before/after of what the installer looks like.
  - Add a "Manual install" collapsed section for contributors who prefer to do it by hand.
- **MIRROR**: Current README structure (headers, badges).
- **IMPORTS**: N/A (markdown).
- **GOTCHA**: README is on the landing page — keep the Quickstart under 30 lines so people don't scroll past it.
- **VALIDATE**: Render the markdown locally (or via GitHub preview); Quickstart still fits above the fold; manual-install details still discoverable but not in the way.

### Task 15: Update CHANGELOG.md for 0.2.0 (or 0.1.1)
- **ACTION**: Add a new entry describing the installer rewrite.
- **IMPLEMENT**: New `## [0.2.0] — 2026-04-XX` section above 0.1.0. Sections: Added (installer, setup.ps1), Changed (setup.sh is now a shim, pyproject deps split into extras), Test (new test file, CI smoke-test job).
- **MIRROR**: Current `CHANGELOG.md` 0.1.0 entry structure.
- **IMPORTS**: N/A (markdown).
- **GOTCHA**: Version number choice — if the runtime pipeline didn't change, 0.1.1 is more honest than 0.2.0. User can decide; plan assumes 0.2.0 but both are fine.
- **VALIDATE**: `pyproject.toml` version bumped to match. `git log` shows the CHANGELOG edit in the same commit as the installer.

---

## Testing Strategy

### Unit Tests (in `learn_video/tests/test_installer.py`)

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_python_ok_311_plus` | `sys.version_info=(3,11,0)` | `True` | — |
| `test_python_ok_rejects_310` | `sys.version_info=(3,10,9)` | `False` | Edge of range |
| `test_ffmpeg_found_returns_path` | Mocked `which("ffmpeg")=/usr/bin/ffmpeg` | `Finding(found=True, path="/usr/bin/ffmpeg", install_cmd="")` | — |
| `test_ffmpeg_missing_darwin` | `platform="Darwin"`, `which=None` | `Finding(found=False, install_cmd="brew install ffmpeg")` | — |
| `test_ffmpeg_missing_linux` | `platform="Linux"`, `which=None` | install_cmd contains "apt install ffmpeg" | — |
| `test_ffmpeg_missing_windows` | `platform="Windows"`, `which=None` | install_cmd contains "choco install ffmpeg" | — |
| `test_resolve_venv_python_windows` | `platform="Windows"`, path=`.venv` | `.venv/Scripts/python.exe` | — |
| `test_resolve_venv_python_posix` | `platform="Linux"`, path=`.venv` | `.venv/bin/python` | — |
| `test_parse_pack_numeric` | `"1"` | `"lite"` | — |
| `test_parse_pack_name` | `"full"` | `"full"` | — |
| `test_parse_pack_invalid` | `"hmm"` | raises `ValueError` | — |
| `test_write_env_file_atomic` | Existing `.env` with `FOO=bar`; adds `GEMINI_API_KEY=x` | Final file has both lines; `.env.tmp` does not exist after | Pre-existing file |
| `test_write_env_file_redacts_log` | capturing stderr while writing | Stderr never contains the key value | Security |

### Edge Cases Checklist
- [x] Empty input to pack selection
- [x] Invalid pack name (numeric out of range, unknown name)
- [x] `.env` already exists with unrelated keys — must be preserved
- [x] Non-interactive (no tty) — require `--yes` + `--pack` or fail clearly
- [x] Windows path separators don't leak into POSIX output
- [x] Missing Python 3.11+ — clean message + exit 3
- [x] Missing ffmpeg — warn + install hint, continue
- [x] pip install failure — show last 30 lines, exit 3
- [x] getpass returns empty string — re-prompt (or accept if user confirms "leave empty")
- [x] stdin redirected (pipe) — detect, fall back gracefully
- [x] Terminal without utf-8 — ASCII fallback for spinner and box-drawing
- [x] Re-running installer over existing venv — detect, offer to reuse
- [x] Permission denied creating venv — clear error pointing at writable location

---

## Validation Commands

### Static Analysis
```bash
python -m compileall -q scripts/ learn_video/
```
EXPECT: Zero compile errors on Python 3.11, 3.12, 3.13.

### Unit Tests
```bash
python -m unittest discover -s learn_video/tests -t . -v
```
EXPECT: 85+ tests pass (74 existing + ~12 new for the installer).

### Non-interactive end-to-end on Linux/macOS
```bash
python scripts/install.py --yes --pack=dev --no-venv --skip-smoke-test \
  --gemini-key=dummy-AIza-test
```
EXPECT: Exit 0. `.env` contains `GEMINI_API_KEY=dummy-AIza-test`. No venv created (flag). Pip installed extras dev.

### Non-interactive end-to-end on Windows PowerShell
```powershell
.\setup.ps1 --yes --pack=lite --no-venv --skip-smoke-test --gemini-key=dummy-AIza-test
```
EXPECT: Same result; no PowerShell execution policy errors after `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

### Interactive smoke test
```bash
./setup.sh
# Walk through all prompts manually. Choose lite pack. Paste a dummy key.
```
EXPECT: All 6 steps progress; final banner prints; `.env` written; `venv_python -c "import learn_video"` succeeds.

### Installer UX inspection
- [ ] ✓ and ✗ glyphs render correctly on macOS Terminal, iTerm, Windows Terminal, VS Code integrated terminal, Alacritty.
- [ ] Spinner updates smoothly on a tty; falls back to line-per-event when stdout is piped.
- [ ] Hidden-input prompt actually hides on all target terminals (or warns if not).
- [ ] Keys never appear in stdout/stderr after capture.
- [ ] Re-running the installer over an existing setup is safe.

---

## Acceptance Criteria

- [ ] `python scripts/install.py --yes --pack=lite --no-venv --skip-smoke-test --gemini-key=x` exits 0 on every OS in the CI matrix.
- [ ] `./setup.sh` on macOS/Linux/git-bash and `.\setup.ps1` on Windows PowerShell both delegate to the Python installer and pass flags through.
- [ ] Interactive flow: all 6 steps visible, prompts well-labeled, defaults obvious.
- [ ] `.env` written correctly; pre-existing entries preserved.
- [ ] `pyproject.toml` has `lite`, `full`, `dev` extras groups; `pip install .[lite]` resolves to a smaller install than `.[full]`.
- [ ] README Quickstart leads with the new installer; manual path still present.
- [ ] 74 existing tests still green; new installer tests added and green.
- [ ] CI workflow runs the installer non-interactively and stays green on 6 matrix cells.
- [ ] CHANGELOG updated. `pyproject.toml` version bumped.
- [ ] Zero new runtime dependencies for the installer (stdlib only).

## Completion Checklist

- [ ] Code follows `learn_video/errors.py` error-taxonomy spirit (clear error messages with fix hints)
- [ ] Subprocess calls match `learn_video/ingest.py:31-45` pattern (capture_output=True, text=True, explicit timeout)
- [ ] `shutil.which` usage matches `learn_video/ffmpeg_util.py:10-16`
- [ ] Status output follows `learn_video/logging_.py` stderr style, `[N/6 STEP]` prefix
- [ ] Argparse style matches `learn_video/cli.py:39-78`
- [ ] Unit tests follow `learn_video/tests/test_ingest_format.py` pattern
- [ ] No hardcoded paths or personal usernames
- [ ] No API keys or secrets in logs or test fixtures
- [ ] Self-contained — contributor can implement from this plan without reading other docs

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Spinner ANSI codes break cmd.exe / old Windows terminals | Medium | Low | Detect tty + encoding; ASCII fallback; never hard-fail on glyph |
| `getpass.getpass()` prints key visibly on some git-bash builds | Medium | Medium (security) | Detect via writing a test char to `/dev/tty`; warn + fall back to `input()`; always accept piped stdin for CI |
| Inline self-reference `learn-video[lite]` in `full` extras requires pip ≥ 21.2 | Low | Low | Already have `pip install --upgrade pip` in installer step 0; workflow uses pip ≥ 23 |
| Users who skip installer and `pip install -r requirements.txt` get less-minimal install than extras | Low | Low | Keep `requirements.txt` as-is (pointing to `.[full]`) so it's equivalent for unsuspecting users |
| PowerShell execution policy blocks unsigned `setup.ps1` | Medium | Low (user-fixable) | Document `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in README next to the PowerShell line |
| Interactive flow hangs in CI or Dockerfile that expected `./setup.sh` to run silently | Medium | Medium | `sys.stdin.isatty()` detection + require `--yes --pack=...` non-interactively, with a clear error message pointing at the flag |
| Installer's `pip install .[pack]` installs over the user's existing venv in unexpected ways | Low | Low | Always compute `venv_python` from the resolved venv path; never invoke `sys.executable` for package installation after step 2 |
| Breaking change: users who currently do `pip install -r requirements.txt` get a different dep set after extras split | Medium | Low | Keep `requirements.txt` as a mirror of `.[full]`; add a header comment noting this |

## Notes

- **Why stdlib-only instead of `rich`?** `rich` is genuinely nicer, but it's a 2MB dep that users would need to bootstrap BEFORE the installer runs (chicken-and-egg). Stdlib + ANSI codes is boring but always works.
- **Why `scripts/install.py` and not `learn_video/install.py`?** The installer has to run before the package is installed. Placing it inside the package would require users to first `pip install .` — defeating the point.
- **Why keep `requirements.txt`?** CI ecosystems, Dockerfile patterns, and older tooling lean on `pip install -r requirements.txt`. Keeping it as a mirror of `.[full]` costs one line of maintenance per release and preserves compatibility.
- **Why an ASCII fallback at all?** Some users are on Windows cmd.exe or CI environments where utf-8 output is mangled. Graceful degradation matters more than prettiness.
- **Future extension, out of scope now**: a `python scripts/install.py doctor` subcommand that re-runs prereq + smoke-test without touching the venv. Would pair well with improvement #2 (`learn-video demo` subcommand) from the roadmap.
- **Version choice**: 0.2.0 signals the UX upgrade; 0.1.1 would also be defensible. Plan assumes 0.2.0. If runtime pipeline stays unchanged, 0.1.1 is arguably more honest. User decides at release time.

**Confidence Score**: 9/10 — single-pass implementable. The one unknown is terminal-emulator quirks (getpass behavior, ANSI support) across the long tail of Windows setups; mitigated by detection + fallbacks but may reveal edge cases during real-user testing.
