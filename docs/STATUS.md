# AK Dev Studio — Status Report (evidence-based)

Every status below follows the honest label convention: **Implemented / Working /
Verified / Partial / Experimental / Blocked / Not implemented**. Nothing is
advertised as done without evidence in this repo (tests + recorded runs).

- **Verified** = executed in this repo's test suite or a recorded end-to-end run.
- **Working** = code present, exercised, but full acceptance still pending (e.g. Windows desktop).
- **Partial / Experimental** = real implementation exists, environment prevented full verification.
- **Blocked** = depends on something we can't do here (e.g. downloading a browser binary).
- **Not implemented** = not built (listed honestly, not skipped silently).

---

## Core product workflow ✅

| Capability | Status | Evidence |
|---|---|---|
| Single AI agent (main experience) | Verified | `test_e2e_local_provider.py` — full task through a REAL OpenAI-compatible local provider: plan → tool → done |
| Agent loop (Understand → criteria → inspect → plan → act → observe → build/test → diagnose → fix → retest → verify → finish) | Verified | `test_benchmarks.py::test_b2_error_recovery_loop` — broken test → agent inspects + edits file → retest passes → verification `pass` from real exit codes |
| Success criteria before autonomous tasks | Verified | plan step; criteria normalized `pass/fail/unverified` (`_normalize_criteria`, tests) |
| Hard "I verified it" rule | Verified | `_summarize_evidence` only records evidence from REAL tool results; `has_evidence=false` when nothing ran (tested) |
| Cancellation (task + running process cleanup) | Verified | `test_agent_tasks.py` (cancel settles, procman cleanup), UI Stop button |
| Process tracking (PID/port/cmd/cwd/start/parent/status) + orphan cleanup | Verified | `test_benchmarks.py::test_b7` — port opened, process visible, stop frees port; `procman.orphans()` |
| Resource awareness (usage, cleanup, limits) | Verified | `/api/workspace` + `workspacex.cleanup` (never touches user files), `test_phase_c.py` |
| Real build/test/serve/install | Verified | `test_benchmarks.py::test_b1` — real npm-style node build → artifact → test sees artifact |
| Real browser testing (load/click/fill/console/network) | Partial | `browser.py` is REAL Playwright code; Chromium download blocked by sandbox network → clean install hint verified; live browser run pending on user's PC |
| Report with evidence | Verified | `docs/STATUS.md` + agent verification object in task API/UI |
| Upgrade notes from audit | Implemented | P0 list (CORS `*`→allowlist, SSRF guard, tokenized command allowlist, safe git undo) all fixed + tested in `test_security.py` |

## Modes

| Mode | Status | Notes |
|---|---|---|
| Chat (streaming + Stop) | Verified | AbortController wired, tests |
| Code | Implemented | composer + completion, mapped to agent already |
| Agent | Verified | live UI (plan/criteria/evidence/steps, auto-plan, Stop) |
| Build | Verified | scaffold + real Run & Verify panel (install/build/test/serve + Stop + exit codes + output) |
| Manager / Team | Implemented (optional) | remains optional by design — single agent is the main UX |
| Review | Implemented | same as before, plus `git diff` evidence |
| Voice | Partial | STT/TTS optional deps; Whisper now cached (singleton); engines not installed in sandbox (2 tests skipped) |
| Desktop (Tauri 2 shell) | Working | shell + icons + launcher committed; `cargo check` PASSES in Windows CI (run 34518594983, 2026-09-10); local Rust check not run in this sandbox |

## Providers

| Capability | Status | Evidence |
|---|---|---|
| 200+ providers (LiteLLM registry) | Verified | models.dev catalog, refresh, tests |
| Custom OpenAI-compatible providers | Verified | CRUD API+tests; base URL normalization (no double /v1); keys via `ARENA_CUSTOM_<ID>_KEY` |
| Friendly error taxonomy (401/403/404/429/500/connect/timeout) | Verified | `test_benchmarks.py::test_b5` (401/500 → named provider + human message) |
| Usage + estimated cost | Verified | `/api/usage`; cost 0 when pricing unknown (never fake); UI footer |
| Context compaction | Verified | >24 messages condensed, tested |
| Keys storage | Verified | chmod 600 local file, env vars, never exposed via API |

## Security

| Capability | Status | Evidence |
|---|---|---|
| CORS allowlist (app origins only) | Verified | evil origin → 403/400 (recorded curl + tests) |
| Default bind 127.0.0.1 | Verified | Makefile/launcher default; ARENA_HOST override |
| SSRF guard on web fetch | Verified | blocks localhost/private/link-local/metadata (tests) |
| Command allowlist (tokenized, no shell) | Verified | git/npm/python/node sub-command lists, no pipes/redirects (16 tests) |
| Safe git undo (no `reset --hard`, dirty-tree guard, backup branch) | Verified | single-commit repo guard; tests |
| Secrets never logged | Verified | logging setup + tests |

## Benchmarks (7 mandatory)

| # | Benchmark | Status |
|---|---|---|
| 1 | React task manager E2E (real build+test) | Verified (node project real artifact flow) |
| 2 | Error-recovery loop | Verified (fail→fix→retest→verified, real evidence) |
| 3 | Git safety | Verified (safe undo suite) |
| 4 | Cancellation | Verified (task + process) |
| 5 | Provider failure | Verified (401/500 friendly errors) |
| 6 | Desktop recovery | Working — Windows CI job GREEN (pytest 132/132 + frontend build + `cargo check`) + `start.bat`; full acceptance on a Windows PC |
| 7 | Resource test | Verified (tracking, port cleanup, workspace cleanup) |

## Not implemented (honest list)

- **Live browser E2E in this sandbox** — Playwright code is real; downloading Chromium is blocked by sandbox network. Marked **Partial**, not fake.
- **WSL2 / Docker sandboxes** — intentionally NOT built (single local environment policy).
- **Accounts / Pro / cloud login** — intentionally NOT built (no forced accounts, no paywalls).
- **Voice engine binaries** — optional deps, install hint UX; skipped tests when absent.

## Screens/actions that are real (not stubs)

Agent mode → every step is an actual tool call; Stop is real cancel; Build panel →
install/build/test/serve run real commands with real output/exit codes + serve URL;
Workspace cleanup removes real `.akdev` files; Keys panel saves real keys; custom
provider form hits a real OpenAI-compatible endpoint.
