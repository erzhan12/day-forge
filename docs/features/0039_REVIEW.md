# Feature 0039 — External Code Review Trail

Playwright e2e harness refactor: shared `test-utils.mjs`, `backend/scripts/*.py`
seed scripts (driven via `manage.py shell -c` + `runpy.run_path`), N+1 regression
test for `select_related("daily_review")` in `ai_generate_draft`, Makefile `e2e*`
targets.

## External review trail — iteration 1

- **Engines:** codex (`gpt-5.6-sol`, read-only sandbox) + cursor agent (`--mode ask`), parallel.
- **Rounds:** 1.
- **Scope:** `git diff HEAD` (28 modified files) + new untracked `backend/scripts/*.py`,
  `backend/tests/test_ai_views_draft_nplus1.py`, `backend/tests/test_seed_scripts.py`,
  `frontend/scripts/playwright/test-utils.mjs`, `README.md`.

### Findings (deduped across engines)

| # | Sev (raised) | Finding | Verdict |
|---|---|---|---|
| A | P2 (both) | `--cleanup` teardown does not wrap the seed→scenario span: `seed(...)` + `chromium.launch()` run **before** the cleanup-bearing `try/finally` in all 17 schedule-seeding scripts, so a failure after seed but before the `try` leaks seeded rows when `--cleanup` is passed. | **VALID, reclassified P3, DEFERRED to user** |
| B | P2 (codex) | `seed_template.py:29` `template_create` mode uses `Template.objects.create` → non-idempotent, would raise IntegrityError on the unique `(user, type)` constraint if repeated. | **REJECTED** |
| C | P2 (cursor) / P3 (codex) | Seeder unit tests only cover `chat_titles`; `localdate`, `user_exists`, `rate_before`, `rate_after`, and the `categories`/`moves`/`overlap`/`draft`/`chat` audit snapshots — all parsed by `.mjs` scripts — were untested. | **ACCEPTED (P3), FIXED** |
| D | P3 (both) | `test-utils.mjs` exports `failExit` (a `process.exit()` helper that bypasses `finally`); dead after the cleanup refactor — no script imports it. | **ACCEPTED, FIXED** |
| E | P3 (codex) | `tasks/todo.md:477` N+1 item still unchecked and recommends the rejected `run_draft`-stub approach. | **ACCEPTED, FIXED** |
| F | P3 (cursor) | `make e2e` help text says only "needs dev stack", omits `LLM_API_KEY`. | Recorded, not fixed (cosmetic). |
| G | P3 (cursor) | Prefer `process.exitCode` + return over bare `failFast` throw in scripts without a `catch`. | Recorded, not fixed (cosmetic; `throw` still runs `finally`). |

### Verification evidence for verdicts

- **A — VALID but reclassified P3, deferred.** The plan (`0039_PLAN.md:585-592`) explicitly
  mandates the teardown wrap the whole seed→scenario span, and the implementation does not — a
  genuine plan-conformance gap in all 17 scripts. Reclassified P3 because the real-world impact is
  negligible: `--cleanup` defaults **off** (a failed run is meant to leave data for post-mortem),
  the seeds are `update_or_create`/idempotent (overwritten on the next run), and the only trigger is
  a `chromium.launch()`/`newContext()` failure — which kills the whole run regardless, making a
  leaked reusable draft row inconsequential. The fix is a 17-file restructure (declare `let browser`,
  move `seed()` + launch into a top-level `try`, guard `browser?.close()`) with no CI to catch a
  regression, so it is surfaced to the user as a decision rather than auto-applied.
- **B — REJECTED.** `template_create` is non-idempotent **by design** — the plan models the three
  template operations as separately-timed steps. Its sole caller, `regenerate-422-fallback.mjs`,
  runs `template_create` (`:178`) exactly once, always after `template_delete` (`:101`), and the
  script's first op `template_seed_initial` (`:50`) does `Template.objects.filter(user=user).delete()`
  which wipes all templates on every rerun. So no code path invokes `template_create` against an
  existing row. Not a bug.
- **C — FIXED.** Added `test_schedule_seeder_userless_and_rate_snapshot_contracts` and
  `test_schedule_seeder_audit_snapshot_contracts` to `backend/tests/test_seed_scripts.py`, asserting
  exact stdout for `localdate`, `user_exists` (True/False), `rate_before`, `rate_after`, and the
  `categories` + `moves` audit snapshots (the load-bearing contracts parsed by the `ai-command-*` /
  draft scripts).
- **D — FIXED.** Removed the unused `failExit` export from `test-utils.mjs`.
- **E — FIXED.** Marked the N+1 todo item done and rewrote it to describe the shipped two-layer test
  and why the `run_draft`-stub approach was rejected.

### Verification status
- `uv run pytest backend/tests/test_seed_scripts.py backend/tests/test_ai_views_draft_nplus1.py -q` → **11 passed**.
- `uv run ruff check backend/` → **All checks passed**.

### Result
Zero valid P1/P2 remaining (A reclassified P3 + deferred, B rejected). Tests + lint green.
**SUCCESS** — pending the user's decision on finding A.

---

## External review trail — feature/0039-followups (post-merge cleanup)

Branch `feature/0039-followups` implements the three deferred 0039 follow-ups:
① `postWithCsrf` throws on missing CSRF cookie (uniform `{status, body}` return; 4 dead
`.error` guards removed); ② `_required`/`_json`/`_user` hoisted to `scripts/__init__.py`
across all 6 seeders; ③ finding A — seed→launch wrapped in the cleanup-bearing `try/finally`
across all 17 schedule-seeding scripts.

- **Engines:** codex (`gpt-5.6-sol`, read-only) + cursor agent (`--mode ask`), parallel, 1 round.
- **Scope:** `git diff main` (26 files).
- **Result:** BOTH engines returned **NO P1/P2 FINDINGS**. Only P3s.

| # | Sev | Finding | Verdict |
|---|-----|---------|---------|
| a | P3 (both) | Missing-`SEED_*` → `RuntimeError` untested for `seed_cleanup`/`seed_prefs`/`seed_template`/`seed_analytics_reviewed` | **ACCEPTED, FIXED** |
| b | P3 (codex) | Todoist `created=False` case untested | **REJECTED — stale**; commit `73f…` added that assertion (`test_seed_scripts.py` reset-ensure re-run) |
| c | P3 (both) | `context`/`chatCalls` over-hoisted to module scope in 3 chat/skipped scripts | **ACCEPTED gap, not fixed** — cosmetic; tightening risks a ReferenceError on a nit, not worth it |

- **a — FIXED.** Added `test_migrated_seeders_raise_runtimeerror_on_missing_required_env` asserting
  each migrated seeder raises a variable-naming `RuntimeError` (not bare `KeyError`) when its required
  `SEED_*` var is absent — the regression guard for the hoist's whole purpose.

### Verification status (followups)
- `uv run pytest backend/tests/test_seed_scripts.py -q` → **12 passed**.
- `uv run ruff check backend/` → **All checks passed**.
- `node --check` on all 17 restructured scripts + `test-utils.mjs` → pass. (No dev stack available
  to run the browser flows; ③ is syntax + structure verified, not e2e-exercised.)

### Result (followups)
Zero valid P1/P2 (both engines). One P3 fixed, one rejected as stale, one recorded as accepted
cosmetic gap. Tests + lint green. **SUCCESS.**
