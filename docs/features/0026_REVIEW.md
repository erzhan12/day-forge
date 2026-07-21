# Feature 0026 — External calendar → timeline + travel rules: code review

Branch `feature/0026-external-event-to-timeline`, rebased onto main (post-0025).
Plan: `docs/features/0026_PLAN.md`. Issue #97.

**Scope:** 28 files / ~3550 lines committed in 3 commits, plus the uncommitted
review fixes recorded below.

## External review trail

Engines: **codex** (`codex exec --sandbox read-only`) and **cursor agent**
(`agent -p --mode ask`), run in parallel, **4 rounds**, with plan-conformance
checking enabled (unlike 0025, which had no plan file).

Findings: raised **28** deduped — accepted **20**, rejected **3** with evidence,
recorded as accepted gaps **5**. **Zero P1 at any round.** Four P2s were found
and fixed; two of those were severity promotions from a P3 report.

Every round found something substantive, so the convergence guard never fired.
Notably, rounds 2–4 increasingly found defects **in the review fixes themselves**
rather than in the original feature — including two in tests this review added.

### Round 1

| Finding | Verdict |
|---|---|
| `Schedule.vue` set `travelRulesReady = true` even when the initial `listRules()` failed. The retry is gated on `!ready`, so one failed fetch stranded `travelRules` at `[]` for the page's lifetime — every later add silently produced an unpadded block with no error. | **P3 → P2, fixed.** Ready is now set only on success. |
| `block_detail` enforced granularity on every *supplied* time; `reorder_blocks` only on *changed* times. `RULES.md` documented the changed-times rule as applying to both. Not reachable via the UI (the frontend PATCHes only `title`/`is_completed`), but the two sibling paths diverged and the knowledge base was wrong. | **Fixed in code**, not the doc, so the documented rule became true. + 2 regression tests. |
| Omitted-order create used `max_order + 1` with no `MAX_ORDER` clamp, so a rule at the bound could store an order its own PATCH validator rejects. | Fixed (clamped). |
| No test for `TravelRulesList.bumpOrder`'s deliberately inverted direction. | Added, **mutation-verified**. |
| No coverage for `ExternalEventsPanel`'s add button, `useSchedule.createBlockFromEvent`, or TravelRule unauth write verbs. | Added. |

### Round 2

| Finding | Verdict |
|---|---|
| The round-1 fix retried the fetch but never checked the retry's result: if it also failed, the dialog still opened seeded from `[]` and Confirm silently created an unpadded block. Same silent-wrong-result class, one layer deeper. | **P2, fixed** — new `rulesUnavailable` prop renders a warning, so a rules outage is distinguishable from a genuine no-match (both otherwise prefill 0/0/`other`). |
| `TravelRulesList.test.ts` fixture used `minutes_before`/`minutes_after`, which do not exist — an `as TravelRule` cast suppressed the type error. **A defect in this review's own test.** | Fixed: real field names, cast removed so `vue-tsc` enforces the shape. |
| `docs/api.md` still said supplied times require 5-minute increments — stale as of the round-1 fix, **introduced by this review**. | Fixed. |
| Rapid Add clicks fanned out parallel `listRules()` GETs. | Fixed (shared in-flight promise). |
| Equal-order reorder branch failed silently. | Fixed (row error). |
| Ghost duration duplicated `useDrag`'s clamp+round math and had drifted. | Fixed by extracting `clampedDragDuration`, shared by both. |

### Round 3

| Finding | Verdict |
|---|---|
| `handleAddToSchedule` awaited the rule fetch without capturing the clicked date; navigating during the await paired the stale event with the newly-viewed day (issue #21 class). | **P2, fixed** — captures the date and drops stale clicks. |
| Round 2 unified the ghost *height* but `startDrag` still seeded the label from **raw** times, so a `00:00–06:30` block showed a 30-min ghost at 06:00 labelled "00:00–06:30" until the first pointermove. Half-fixed by this review. | **P2, fixed** — label seeds from the clamped span. |
| The undo test named "snapshotted BEFORE the create" never asserted call order. **This review's own test.** | Fixed with `invocationCallOrder`; mutation-verified. |

### Round 4

| Finding | Verdict |
|---|---|
| The round-3 date guard covered only navigation *during* the await. With the dialog already **open**, the live `props.date` meant an overnight event — which still intersects the next day — kept Confirm enabled and would write that day's slice, at different times than the user saw. | **P2, fixed** — the date watcher now calls `closeAddDialog()`, matching its sibling resets (chat thread, in-flight draft, undo toast). |
| The drag-label comment claimed a "snap-rounded span"; only the duration is rounded, the start is merely clamped. | Comment corrected. |
| The round-3 label-seed fix was unpinned (assertions ran only after `fireMove`). | Assertion added before any move. |
| `"up" never increases order` asserted only `< 2`, accepting a wrong jump to 0. | Tightened to the exact swap value. |

### Rejected (with evidence)

1. **"The from-event endpoint violates the plan by defaulting an omitted
   `category` to `other`."** (codex, round 2.) The plan marks only `title` as
   required — step 6 reads "Validate `title` (required, ≤ 255) and `category`
   (in `VALID_CATEGORIES`)". `"other"` is itself a member of that set, and the
   hole the plan actually warned about (an unhashable `category` reaching a set
   lookup and raising a 500) is closed by an explicit
   `isinstance(data["category"], str)` guard, so a non-string returns 400.

2. **"The zero-length / outside-day dialog tests never click, so
   `handleConfirm`'s internal `confirmDisabled` guard is unpinned."** (both
   engines, round 3.) The stated rationale — "VTU invokes `@click` on disabled
   buttons" — is false. `@vue/test-utils`' `trigger()` no-ops on a disabled
   element, and jsdom does not fire click handlers on disabled buttons either.
   **Verified by mutation: deleting the internal guard leaves all 12 dialog
   tests green.** That guard is unreachable from the DOM and no click-based
   test can pin it. The `disabled` attribute is the real protection and *is*
   mutation-verified — removing either gate from `confirmDisabled` fails a
   test. The engines were right that the test comment overclaimed, so the
   comment now states exactly what is and is not covered.

3. **"Navigating with the dialog open posts to the wrong schedule."**
   (codex, round 4, as originally framed.) Initially rejected because
   `computeEventBlockTimes` returns `null` off-day and disables Confirm —
   **that rejection was wrong**, and cursor supplied the missing case in the
   same round: an overnight event still intersects the navigated day, so
   Confirm stays enabled. Reversed and fixed (see round 4).

### Accepted gaps

- **Non-atomic two-PATCH reorder swap** — a first-succeeds/second-fails
  sequence can leave duplicate `order` values. Identical pre-existing pattern
  in `templates_mgr`'s `RulesList`; a proper fix needs a dedicated atomic swap
  endpoint and would diverge the two sibling components. Out of scope.
- **Concurrent default-order creates** can race `max(order)+1` outside a lock
  and be born with equal orders. Per-user, 100-rule cap, and the duplicate
  degrades only to the equal-order branch, which nudges by ∓1 and now surfaces
  a row error.
- **`MAX_ORDER` clamp trades born-distinct for in-range at the bound** —
  documented inline; reaching it takes a deliberate PATCH to 1,000,000.
- **`closeAddDialog()` in the date watcher is not unit-tested.** Driving it
  needs `ExternalEventsPanel` to render, which requires a connected calendar —
  a file-wide `useCalendar` mock that would change rendering for every other
  test in `Schedule.test.ts`. Recorded as a `KNOWN TEST GAP` comment there
  rather than shipping fragile scaffolding to claim coverage.
- **`travelRules.ts` classifies `23:00(prev) → 00:00(viewed)` as outside-day
  rather than zero-length.** Confirm is blocked either way; only the hint
  differs.

### Out of scope (pre-existing, deferred to `tasks/todo.md`)

`frontend/src/utils/externalEventPast.ts` fades overnight events as "past"
while they are still running: it compares the *clock* minutes of `ev.end`
against `nowMinutes` with no day-delta fold, so a `23:00 → 00:30 (+1d)` event
reads as ended from 00:30 onward. Same UTC→local class of bug that
`computeEventBlockTimes` was written to avoid, in the very panel that owns the
Add button. **The file is unmodified on this branch** (confirmed by
`git diff`), so it was left alone to keep this PR scoped.

## Verification

`uv run pytest backend/tests/ -q` → **739 passed**
`cd frontend && npm test` → **560 passed** (51 files)
`npx vue-tsc --noEmit` → clean
`uv run ruff check backend/` → clean

Tests added by this review: 5 backend, ~28 frontend. Mutation-verified:
reorder direction (inverting fails 4/5), both dialog Confirm gates
(independently), and undo call ordering.

## Result

**STOPPED after 4 rounds** — not by the convergence guard (every round found
something real) but because returns are shifting: rounds 3 and 4 largely found
defects in this review's own fixes and tests rather than in the feature.

Zero valid P1/P2 outstanding. Not committed.

**Manual smoke is still outstanding** and matters more than usual here: the
off-grid lifecycle (complete / rename / drag / undo on a `14:07–14:33` block)
and the travel-rule reorder direction are the paths where a missed call site
produces a confusing 400 rather than a test failure.
