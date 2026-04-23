# Local Review: feat/friendly-installer

**Reviewed**: 2026-04-23
**Branch**: `feat/friendly-installer`
**Files changed**: 10 (3 created, 7 modified) + 28 new tests + planning artifacts
**Decision**: **APPROVE with comments** — no CRITICAL or HIGH findings. Four MEDIUM items are worth fixing in the same commit; six LOW items are optional nits.

## Summary

Installer rewrite is functionally correct, well-tested (102/102), and compiles clean. The installer keeps to stdlib as promised, follows the existing `learn_video/` error-taxonomy and logging conventions, and handles secrets (API keys) with hidden input + atomic file writes. A handful of polish items would make the shipped version feel as good as its test suite reads.

## Findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

**M1. `step_smoke_test` reports "passed" without checking the return code** — `scripts/install.py:663-665`

The regex `r"Ran (\d+) tests? in"` matches unittest output whether tests passed or failed. The message `"{N} unit tests discovered and passed"` is technically inaccurate on failures.

```python
match = re.search(r"Ran (\d+) tests? in", (proc.stderr or ""))
if match:
    _ok(f"{match.group(1)} unit tests discovered and passed")  # always "passed"
```

**Fix**: gate the success message on `proc.returncode == 0`.

**M2. `pip install --upgrade pip` result is discarded silently** — `scripts/install.py:472-477`

If the upgrade fails (offline, proxy, certificate), the installer continues and only surfaces the error later when the real install fails with a less-targeted message.

```python
with Spinner("upgrading pip") as sp:
    subprocess.run(pip_cmd, capture_output=True, text=True, timeout=120)
    # ↑ returncode ignored
```

**Fix**: check `proc.returncode`; warn (don't hard-fail) if non-zero so pre-existing modern pip users still proceed.

**M3. No timeout on the main pip-install subprocess** — `scripts/install.py:485-511`

`subprocess.Popen(...).wait()` has no upper bound. A stuck network would leave the spinner running indefinitely with no way to recover except Ctrl+C.

**Fix**: track start time; kill the subprocess if it exceeds 30 min (`proc.wait(timeout=1800)`); clean up on timeout.

**M4. `write_env_file` doesn't sanitize key values** — `scripts/install.py:270-319`

Values are written verbatim. A value with an embedded newline (malicious paste, shell-quoting mishap in `--gemini-key`) would inject extra lines into `.env`. Not a realistic security exploit (the user would have to paste a crafted value into their own prompt), but defensive rejection is cheap.

**Fix**: strip or reject values containing `\n`, `\r`, or `\0`. Also guard against `=` inside the value (rare, but would make the line ambiguous).

**M5. CI installer smoke test uses `--pack=dev` (~350 MB × 6 matrix cells)** — `.github/workflows/tests.yml:45`

The plan document predicted ~5s per cell; reality is 60–90s per cell because the test runner has no preinstalled langgraph/langchain-*. Six matrix cells means ~6–10 minutes of extra CI time per push, and the installer's own logic is the same regardless of pack.

**Fix**: switch CI smoke to `--pack=lite` (~200 MB, faster) — same code path proves the installer works cross-platform without exercising the provider SDKs we don't use in unit tests anyway.

### LOW

**L1. Unused imports** — `scripts/install.py:27,31`. `from contextlib import contextmanager` and `from typing import Iterator` aren't referenced. Drop them.

**L2. One-line function definitions** — `scripts/install.py:71-73`. PEP 8 prefers block form for `def`. Cosmetic.

**L3. Misleading `except getpass.GetPassWarning`** — `scripts/install.py:547`. `GetPassWarning` is emitted via `warnings.warn`, not raised, so this except clause will never fire. Keep `OSError` (that's the real fallback trigger) and drop the Warning.

**L4. `for attempt in range(3)`** — `scripts/install.py:458`. Loop variable unused. Convention: `for _ in range(3)`.

**L5. Unused `as sp` bindings** — `scripts/install.py:407, 476, 628, 653`. `with Spinner(...) as sp:` never references `sp`. Drop the binding: `with Spinner(...):`.

**L6. `input()` could raise `EOFError` mid-prompt** — `scripts/install.py:370, 393, 402, 459`. If stdin closes unexpectedly (e.g. a pipe breaks), these calls raise uncaught and the installer backtrace-crashes. Not realistic in interactive use; defensive try/except would be nicer but isn't load-bearing.

## Validation Results

| Check | Result |
|---|---|
| Type check | Skipped (no mypy configured) |
| Lint | Skipped (no ruff/flake8 configured) |
| Tests | **Pass** — 102/102 via `python -m unittest discover -s learn_video/tests -t .` |
| Build | **Pass** — `python -m compileall -q scripts/ learn_video/` clean |
| End-to-end installer smoke | **Pass** — `--yes --pack=lite --no-venv --skip-smoke-test --gemini-key=x` completes all 6 steps, `.env` written atomically, exit 0 |
| pyproject.toml parse | **Pass** — version 0.2.0, 5 base deps, `lite`/`full`/`dev` extras |

## Files Reviewed

| File | Change |
|---|---|
| `scripts/install.py` | ADDED (530 lines) |
| `scripts/__init__.py` | ADDED (empty) |
| `setup.ps1` | ADDED (20 lines) |
| `setup.sh` | MODIFIED (69 → 20 lines; now a shim) |
| `pyproject.toml` | MODIFIED (deps split into extras, version 0.2.0) |
| `requirements.txt` | MODIFIED (added header comment) |
| `learn_video/tests/test_installer.py` | ADDED (213 lines, 28 tests) |
| `.github/workflows/tests.yml` | MODIFIED (added installer smoke step + `scripts/` compileall) |
| `README.md` | MODIFIED (Quickstart rewrite) |
| `CHANGELOG.md` | MODIFIED (0.2.0 entry) |

## Security Posture

- No hardcoded secrets. `.env.example` uses placeholders only.
- Subprocess calls all use list-form arguments (no `shell=True`) — no command injection surface.
- API-key input uses `getpass.getpass` with fallback that warns on visibility loss.
- `.env` written via tempfile + atomic `os.replace` — no partial-write corruption.
- Pack choice double-validated (argparse `choices=` + `parse_pack_choice`).
- `install_cmd` strings passed to printouts, never to subprocess — no shell injection via hints.

Overall security: clean.

## Recommendation

Apply M1–M5 in the same commit (about 20 lines of changes total). L1–L6 are optional; I'd take L1, L3, L5 while in the file but can leave L2, L4, L6 for a follow-up.
