# Feature 0036 — Code Review

Rate-limit the account-connect endpoints (CalDAV + Todoist + Habitica).

## External review trail

**Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`agent --mode ask`), run in parallel.
**Rounds:** 1.
**Scope:** `git diff HEAD` (10 files) + untracked `backend/schedules/ratelimit.py`, `backend/tests/test_ratelimit.py`.

### Verdict

Both engines independently returned **NO P1/P2 FINDINGS**. Zero valid
P1/P2 raised → SUCCESS on iteration 1. No code changed this round.

### P3 findings (non-blocking — recorded, not fixed)

1. **codex** — `backend/tests/test_ratelimit.py:39`: TTL test asserts the
   window deadline is unchanged + positive but not ≈ `3600`, so a wrong
   fixed-window duration could pass. *Recorded gap.* The plan
   deliberately chose the non-increasing-deadline assertion over a bare
   `> 1800` threshold to catch sliding-window re-anchoring; an added
   "≈ WINDOW" check is complementary but out of the mandated shape.
2. **codex** — `test_{calendar,todoist,habitica}_sync_views.py`
   (`test_400_body_does_not_consume_token`): name is narrow — the test
   also exercises a 413 (oversized body) branch. Naming nit, not a logic
   gap.
3. **cursor** — `test_settings_validation.py`: zero-raises + valid-default
   covered; no explicit negative (`"-1"`) import-time case. `<= 0` guard
   already handles it; the zero case pins the boundary.
4. **cursor** — three near-identical `TestConnectRateLimit` classes
   (~80 lines ×3) are a maintainability drag, not a bug. Plan flagged
   dedupe as a Cycle-6 "consider", explicitly non-blocking.
5. **cursor** — `docs/api.md` 429 rows don't name the governing env vars
   (unlike the AI 429 rows naming `LLM_*_RATE_LIMIT_PER_HOUR`).
   Consistency nit.
6. **cursor** — no direct unit asserts for `connect_rate_limit_key` /
   `rate_limited_response` (only exercised transitively via view tests).
   Thin gap given plan scope.

### Verification

- `uv run pytest backend/tests/{test_ratelimit,test_settings_validation,test_calendar_sync_views,test_todoist_sync_views,test_habitica_sync_views}.py` — **143 passed**.
- `uv run ruff check` on the changed backend files — **clean**.

### Result

SUCCESS — zero valid P1/P2, tests + lint green. P3s left for the user's
call (all cosmetic / defense-in-depth, none block).

## External review trail — 0036 follow-up (schedules.W002 + test dedup)

Second change set on `feature/0036-followups`: (A) new `schedules.W002`
system check warning on an ineffective connect-rate-limit cache backend;
(B) dedup of the three `TestConnectRateLimit` classes into
`backend/tests/_connect_rate_limit_contract.py`.

**Engines:** codex (`gpt-5.6-sol`) + cursor, read-only, 2 iterations.

**Iteration 1** — both NO P1/P2 on the logic. codex raised one **P2**:
the W002 message ("limit × worker_count", "single-worker nil") was
accurate only for LocMem — `DummyCache` disables the limiter entirely and
`FileBasedCache` is shared-but-non-atomic. **Accepted & fixed**: reworded
the message + docstring to describe all three distinct failure modes.
Also fixed (P3): hint now names `PyMemcacheCache` too; W002 tests moved
from a separate `test_schedules_checks.py` into the canonical
`test_checks.py` (`TestConnectRateLimitCacheWarning`) and strengthened.

**Iteration 2** — both NO P1/P2 on the logic. codex raised a **P2** that
the strengthened tests still asserted only generic substrings.
**Accepted & fixed**: the W002 test now asserts all three failure-mode
keywords (`LocMemCache`/`DummyCache`+`disabled`/`FileBasedCache`+
`non-atomic`) and both hint backends, so a regression to a flat summary or
a dropped memcached hint fails. P3 docstring "non-shared" summary →
"ineffective"; `tasks/todo.md` filename + backend-flattening corrected.

**Declined (P3):** widening the three `.claude/rules/project.md` env-var
entries with the full per-backend breakdown — those lines are
intentionally concise and already name the ineffective set + point to
`schedules.W002`, whose message carries the detail.

**Stopped via convergence guard** after iter 2: both rounds converged on
the same tiny surface (the one warning message's accuracy + locking it),
never a logic defect. **Verification:** `test_checks.py` 21 passed; full
backend suite 896 passed (pre-fix run); ruff clean on all touched files
(3 pre-existing `ai/*` import-sort errors are unrelated and untouched).
