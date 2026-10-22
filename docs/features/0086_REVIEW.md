# 0086 — Review: tight-window gap preference for untimed chat adds (issue #260)

Plan: [0086_PLAN.md](0086_PLAN.md). Branch `feature/0086-auto-place-gap-degrade`, cut from `main` at 995efbb.

## Plan conformance

- `_find_auto_slot` / `_padded_auto_intervals` in `backend/ai/mutation_planner.py` implement Design §1–§9: initial window from chronologically sorted raw occupancy, full-gap `find_slot` first (accepted when it ends inside the initial window), symmetric retry levels derived per call from `AUTO_PLACEMENT_GAP_MINUTES` down through grid multiples to zero, one right-aligned candidate per level checked with a direct half-open overlap test, full-gap fallback, unchanged `no_slot` semantics. `find_slot`, `_earliest_start`, schemas, fingerprints and the replay guard are untouched.
- All 15 planner rows of the plan's Red table exist in `TestAutoPlacementGapPreference`, plus two extra monkeypatch cases (default gap 0 and 7) for the retry-level derivation. The three integration tests, the prompt contract test and the Vitest help-text assertion are present. The four compatibility controls the plan declared as already-green are marked as such.
- Copy and docs: `no_slot` ask drops "with the required gaps"; prompt, `docs/api.md`, `RULES.md`, `docs/ARCHITECTURE.md` and the Settings help text describe the gap as a preference that shrinks only in the initial window.

## Local staged review (5 parallel reviewers: quality, security, performance, testing, docs)

No CRITICAL findings. One WARNING (prompt wording "if the block would otherwise skip it" was ambiguous) and the cheap INFO items were applied before the external round: stale "SOLE overlap guard" comment, no-op `temp_id` filter, `DEFAULT_AUTO_DURATION_MINUTES` in the test helper, gap 0 / gap 7 tests. Deferred INFO: hoisting the pre-existing local `find_slot` import; the `_plan(blocks, …)` helper takes a dummy `[]` when `snapshot=` is passed; the `date` parameter of `test_non_today_tight_window_uses_day_start` never reaches the planner (the view-level test covers the date path); the pre-existing `"5 minutes"` Vitest assertion is now redundant.

## External review trail

Engines: Codex (`gpt-6-astra`, read-only, one run per aspect: quality, security, performance, testing, docs) and Cursor agent (read-only, whole diff with a verification log).

Round 1: all five Codex aspect runs and Cursor returned `NO P1/P2 FINDINGS`. Cursor raised three P3s, all accepted and fixed:

1. `docs/api.md` said the right-aligned end is "before the next block's padded start"; with a zero gap the block touches the next block. Reworded to "no later than the next block's start minus the trial gap".
2. `docs/ARCHITECTURE.md` used «интервал», which that document uses for a block's own interval; the sentence now says «зазор».
3. `backend/ai/prompts.py` described retries only "before the next block"; the day-end case (no block follows) is now named.

Rejected: none.

## Verification

- `uv run ruff check backend/`: clean.
- `make check`: backend 2173 passed, 1 skipped; `vue-tsc` clean; Vitest 104 files / 1410 tests passed.
- `make frontend-build`: production bundle built.

## PR #261 claude-review

Round 1 (b105920): verdict APPROVED, no P0/P1. Applied: P2 hoisted the two deferred `find_slot` imports in `backend/ai/mutation_planner.py` to the module import (no circular import: `free_slot` imports `SlotSuggestion` lazily inside `find_slot`); P3 extended the Settings help text with the day-window-end case. Rejected: P3 "re-sorting inside the retry loop" — `sorted(...)` runs once before the loop; only the padding list is rebuilt per trial, which is intended.

Round 2 (432159a): verdict APPROVED, no P0/P1. Applied: P2 removed the orphaned comment that still explained the function-local `find_slot` import.

Round 3 (c7bd11c): verdict APPROVED, no P0/P1. Applied: P2 the test helper now asserts `action_index` against the enumerated position instead of `list.index()`; P3 unified "initial window" wording in `docs/api.md`.
