# 0035 — Code Review Trail

Feature: fix overnight external calendar events fading as "past" while still
running — DST-safe local day-delta fold in
`frontend/src/utils/externalEventPast.ts` so an event ending on a later local
calendar day (e.g. `23:00 -> 00:30 +1d`) is no longer collapsed to its clock
value and mistaken for past.

## External review trail — iteration 1

**Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`--mode ask`), run in parallel.
**Scope:** `frontend/src/utils/externalEventPast.ts`,
`frontend/tests/externalEventPast.test.ts` (+ untracked `docs/features/0035_PLAN.md`).

**Context:** the worktree originally carried a **stale pre-review copy** of the
plan; the implementation was built from it and so used the un-hardened test
fixtures. The final ext-plan-review'd plan was synced into the worktree before
this review. The production fold itself matched the final plan exactly.

### Findings

| # | Engine(s) | Sev | Location | Verdict |
|---|-----------|-----|----------|---------|
| 1 | codex + cursor | P2 | `externalEventPast.test.ts` Slice 3.1 | ACCEPTED — fixed |
| 2 | codex + cursor | P2 | `externalEventPast.test.ts` (missing Slice 3.2) | ACCEPTED — fixed |
| 3 | cursor | P3 | `externalEventPast.ts` JSDoc | ACCEPTED — fixed |

**Finding 1 (P2, both engines):** the prior-day regression test used a
non-discriminating fixture (`end 2026-05-06T00:30:00`, `nowMinutes = 720`):
`30 <= 720` is `true` under **both** the buggy clock-only compare and the fold,
so it guarded nothing. **Fix:** switched to `timed("2026-05-05T17:00:00",
"2026-05-06T18:00:00")` — end clock-minutes `1080 > 720`, so no-fold returns
`false` (would fail the `toBe(true)` assert) and only the negative-`dayDelta`
fold makes it `true`. Now genuinely pins the sign handling.

**Finding 2 (P2, both engines):** the plan mandated three added tests but only
two were present; the `nowMinutes === null` today-branch preservation test was
missing (existing null calls short-circuit on the past/future viewed-date
guards and never reach the null early-return). **Fix:** added
`it("returns false on today before the first tick (nowMinutes null)")`.

**Finding 3 (P3, cursor):** the `isExternalEventPast` JSDoc still described a
same-day clock-only end comparison. **Fix:** noted the cross-day fold.

**Rejected:** none this iteration. Previously-rejected/deferred items were
correctly not re-raised by either engine: the `Z`-suffixed-UTC-fixture (rejected
during plan review — suite is deliberately naive-ISO/TZ-independent), the
non-reactive `today` computed rollover staleness (documented deferred
limitation), and the DST round-vs-floor TZ-pinned test (by-construction, out of
scope). (codex could not start vitest in its read-only sandbox — an
EPERM on `node_modules/.vite-temp`, an environment quirk, not a test failure;
tests were run directly in the worktree instead.)

**Verification:** `npx vitest run externalEventPast` → 7 passed (4 existing + 3
added); `npm test` (full frontend) → 689 passed / 57 files; `npx vue-tsc
--noEmit` → clean.

**Result:** SUCCESS — zero valid P1/P2, tests + type-check green.
