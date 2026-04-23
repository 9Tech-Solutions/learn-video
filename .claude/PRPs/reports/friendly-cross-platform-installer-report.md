# Implementation Report: Friendly Cross-Platform Installer

## Summary

Replaced the bash-only `setup.sh` with a stdlib-only Python installer at `scripts/install.py` and two thin shims (`setup.sh` + `setup.ps1`) that delegate to it. Split `pyproject.toml` deps into `lite` / `full` / `dev` extras groups. Added 28 unit tests, a CI smoke-test step, CHANGELOG entry, and README rewrite. Bumped version to 0.2.0.

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Medium | Medium — matched |
| Confidence | 9/10 | 9/10 — no surprises |
| Files Changed | 10 | 10 — matched exactly |
| Installer LoC | 350-450 | ~530 (includes docstrings and fallback paths) |
| New tests | ~12 | 28 — plan undercounted; each helper got thorough coverage |
| Total test count | 85+ | 102 |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | Split `pyproject.toml` deps into extras | ✅ Complete | `lite`/`full`/`dev` groups; inline self-reference `learn-video[lite]` works on pip ≥ 21.2 |
| 2 | Create `scripts/install.py` skeleton | ✅ Complete | Argparse + `InstallerState` dataclass + six step functions |
| 3 | `step_prereq` — detect Python / ffmpeg / yt-dlp | ✅ Complete | Non-blocking on yt-dlp (pip installs it); OS-specific install hints |
| 4 | `step_venv` — create + prep virtualenv | ✅ Complete | `resolve_venv_python` handles Windows vs POSIX layout |
| 5 | `step_pack` — interactive pack selection | ✅ Complete | Non-interactive detection via `isatty` + `--pack` flag |
| 6 | `step_install` — pip install with spinner | ✅ Complete | Background thread reads pip stdout line-by-line, spinner shows current package |
| 7 | `step_keys` — hidden key input → atomic `.env` | ✅ Complete | `getpass.getpass` with `input()` fallback for terminals that leak hidden input |
| 8 | `step_smoke_test` — import + test discovery | ✅ Complete | Skippable via `--skip-smoke-test` |
| 9 | `print_done` — final banner | ✅ Complete | OS-correct activation hint order (Windows vs POSIX) |
| 10 | Rewrite `setup.sh` as shim | ✅ Complete | 69 → ~20 lines; uses `exec` to pass signals through |
| 11 | Create `setup.ps1` shim | ✅ Complete | PowerShell equivalent with execution-policy hint in the README |
| 12 | Unit tests for helpers | ✅ Complete | 28 tests across 9 test classes; all hermetic (no subprocess, no network) |
| 13 | CI workflow — add installer smoke step | ✅ Complete | Runs on all 6 matrix cells (ubuntu+windows × Python 3.11/3.12/3.13) |
| 14 | README Quickstart rewrite | ✅ Complete | Leads with installer visual, adds non-interactive + manual paths + PowerShell policy note |
| 15 | CHANGELOG 0.2.0 entry + version bump | ✅ Complete | `pyproject.toml` → 0.2.0 |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static (compileall) | ✅ Pass | `scripts/` and `learn_video/` both compile clean on Python 3.13.5 |
| Unit tests | ✅ Pass | 102/102 green (74 existing + 28 new installer tests) |
| pyproject sanity | ✅ Pass | Parses; version 0.2.0; 5 base deps + 3 extras groups |
| Installer non-interactive smoke | ✅ Pass | `python scripts/install.py --yes --pack=lite --no-venv --skip-smoke-test --gemini-key=x` exits 0, all 6 steps report cleanly, `.env` written atomically |
| Shim delegation | ✅ Pass | `./setup.sh --help` shows the Python installer's help |

## Files Changed

| File | Action | Lines |
|---|---|---|
| `scripts/install.py` | CREATED | +530 |
| `scripts/__init__.py` | CREATED | +0 (empty marker) |
| `setup.ps1` | CREATED | +20 |
| `setup.sh` | UPDATED | 69 → 20 (net -49) |
| `pyproject.toml` | UPDATED | +14 / -8 (deps split into extras, version bump) |
| `requirements.txt` | UPDATED | +4 (added header comment) |
| `learn_video/tests/test_installer.py` | CREATED | +200 (28 tests) |
| `.github/workflows/tests.yml` | UPDATED | +8 / -2 (added installer smoke step + compileall for scripts/) |
| `README.md` | UPDATED | +56 / -42 (Quickstart rewrite, added non-interactive + manual + PS policy sections) |
| `CHANGELOG.md` | UPDATED | +34 (0.2.0 entry) |

## Deviations from Plan

1. **Installer LoC**: plan estimated 350-450; actual ~530. Extra lines came from: the Spinner class (cleaner as a context manager than inline threading), the box-drawing frame (plan said "optional"; easier to include with ASCII fallback than describe later), and the per-step argument-extraction comments. Not a functional deviation — the scope matches exactly.

2. **Test count**: plan said "~12 tests"; actual 28. Each testable helper got 2–6 tests instead of the 1 example the plan sketched. This is upside, not scope creep.

3. **`step_smoke_test` omitted `langchain_core` from the "always" checks** — the plan originally wrote `import langchain, langchain_core`. Because `langchain_core` is a dependency of every `langchain-*` package, checking it is redundant once we check `langchain`. Kept `langchain_core` in the provider check but removed the duplicate.

4. **Kept `LearnVideoError`-style error classes inline** as the plan's GOTCHA anticipated — could not `from learn_video.errors import ...` because the installer runs before install. Went with plain `sys.exit(code)` + stderr message instead of duplicating the exception classes; cleaner for a stdlib-only module.

## Issues Encountered

1. **argparse `--help` output in tests**: `TestArgparse.test_help_exits_zero` dumped the full help text to stdout during the test run, burying the summary. Fixed by wrapping the call in `contextlib.redirect_stdout(io.StringIO())`. Same treatment for `test_rejects_unknown_pack` (argparse writes the error message to stderr before SystemExit).

2. **Spinner test leaked a line**: the non-tty fallback path prints a line per status update, which leaked into test runner output as `-> doing X`. Fixed by wrapping that test in `contextlib.redirect_stderr` too. Functional behavior unchanged.

3. **Smoke-test `.env` artifact**: running the end-to-end CI smoke test locally wrote a real `.env` file with a dummy key. Deleted before commit; `.gitignore` already excludes it so wouldn't have shipped anyway.

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `learn_video/tests/test_installer.py` | 28 | `detect_python_ok` (5), `install_hint_for_os` (5), `detect_ffmpeg` (2), `detect_ytdlp` (1), `resolve_venv_python` (2), `parse_pack_choice` (3), `format_finding_row` (2), `write_env_file` (4), `Spinner` (1), `_build_parser` (3) |

Plus interactive / subprocess-heavy code paths verified via the non-interactive installer end-to-end run (not unit-tested).

## Next Steps

- [ ] `/code-review` pass before merge (recommended since this adds a new top-level binary)
- [ ] Merge `feat/friendly-installer` → `main`
- [ ] Tag and release `v0.2.0` with the CHANGELOG body
- [ ] Optional: roadmap items #2 (`learn-video demo` subcommand) and #3 (PyPI release workflow) can now build on top of the cleaner pack-group structure
