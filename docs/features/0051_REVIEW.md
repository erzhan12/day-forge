# 0051 — Code Review: connect rate-limiter cache-expiry race fix (issue #136)

Feature plan: `docs/features/0051_PLAN.md`
Change surface: `backend/schedules/ratelimit.py`, `backend/tests/test_ratelimit.py`

## Summary of the fix

`consume_rate_limit` recovery branch replaced the unconditional
`cache.set(key, 1, 3600)` (a blind overwrite that let N concurrent callers each
reset the counter to `1` and be admitted) with an atomic `cache.add` →
retry-`incr` loop bounded by `_MAX_RESEED_ATTEMPTS = 3`. One caller wins the
recovery `add` and establishes the shared replacement window; others increment
that shared counter via `incr`. Exhausting the retry budget **fails closed**
(returns `False`). Fixed-window TTL (`CONNECT_RATE_LIMIT_WINDOW_SECONDS = 3600`)
preserved on the reseeded counter.

## Local review (review-fix-loop-staged)

- Categories: Code Quality, Security, Performance, Testing, Documentation.
- **0 CRITICAL, 0 WARNING.** 2 INFO:
  - `test_ratelimit.py` leftover editing-note comment on the rewritten eviction
    test — **fixed** (rewritten to describe the eviction-then-recover scenario).
  - `test_consume_rate_limit_repeated_eviction_fails_closed` originally asserted
    only the `False` return. **Fixed during PR #149 review** (rounds 1-2): it now
    also asserts the reseed warning fires exactly once (`len(reseed_warnings)
    == 1`) and that the full retry budget is consumed before failing closed
    (`add_calls == incr_calls == _MAX_RESEED_ATTEMPTS + 1`).
- Verification: ratelimit unit tests 9 passed; connect-view regression
  (`test_calendar_sync_views`, `test_todoist_sync_views`,
  `test_habitica_sync_views`, `_connect_rate_limit_contract`) 120 passed; ruff
  clean.

## External review trail (ext-code-review)

- Engines: codex + cursor (read-only). Cursor was unavailable for this run;
  codex completed a full pass and independently ran the test suite (120 passed).
- Iterations: 1.
- Findings: raised 1, accepted 0 as blocking, rejected 0, P3-ignored 1.
  - **P3** (codex) — `test_ratelimit.py` repeated-eviction test asserts only
    `False`, not bounded `add`/`incr` call counts or single-warning; a premature
    fail-close or retry-loop log-spam regression could stay green. Non-blocking;
    matches the local-review INFO. Not fixed by design (P3 does not block).
- Verification after review: tests 120 passed, ruff clean. No code changed in
  this round (no P1/P2 to fix).

## Result

Ready to ship ✅ — zero valid P1/P2 across local + external review; full suite
green, lint clean.
