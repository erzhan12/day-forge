# Feature 0067 — External Code Review Trail

Feature: chat-only deterministic backend auto-placement for start-less AI `add`
actions. Reviewed against `docs/features/0067_PLAN.md`. Engines: OpenAI codex
(`gpt-5.6-sol`) + Cursor `agent`, both read-only. All fixes applied by the
orchestrator; nothing auto-written by the engines.

## Local staged review (pre-external)
Five categories (quality/security/perf/testing/docs) via subagents — **NO CRITICAL
ISSUES**. Two WARNINGs folded before external review: added an exact-fit-at-window-end
planner test; documented the `earliest_start` param on `plan_mutations`.

## External review loop

### Iteration 1
Both engines: **NO P1/P2** except one Cursor **P2** (Codex raised same as P3):

- **P2 (accepted, fixed)** — `test_unequal_durations_later_add_may_take_earlier_gap`
  used an empty day, so it passed under plain sequential-append and did not prove the
  plan's common-base "later add may take an earlier gap" decision. Rewritten with a real
  early hole (block `09:35–11:00`, padded `09:25–11:10`) too small for the 60-min add:
  the long add lands `11:10–12:10`, the short 25-min add takes the earlier `09:00–09:25`
  hole — pinned by exact intervals + a strict earlier-start assertion.

P3s folded (cheap, clearly right): `_earliest_start` now consumes `free_slot.GRID_MINUTES`
instead of a hardcoded `5`; `_build_resolution_ask` precedence comment corrected to name
the distinct `no_slot` tier; `prompts.py` module docstring no longer claims the model
fills omitted start/gap; positive assertion added pinning the reworded Hard rule 2.

### Iteration 2
Both engines: **NO P1/P2 FINDINGS** → SUCCESS. Two trivial P3s folded (sentinel tests now
assert exact `== window.day_end`; frontend subtitle test pins the 25-/10-/5-minute
figures).

## Accepted (non-blocking) P3 gaps
- Mixed-outcome precedence: `no_slot` is tested against the `attempted_direction` tier and
  the generic skipped-add branch in both orders, but not paired with a concrete
  suggestion / `direction_required` outcome. The precedence loop is order-invariant by
  construction; covered indirectly.
- `test_duration_minutes_rejects_bad_values` includes `True`/`False`, but those also fail
  the `<=0` / `% 5` checks, so the case does not *uniquely* prove the `is_plain_int` bool
  guard (the guard itself is exercised elsewhere).
- `test_today_never_starts_before_earliest_start` asserts `start >= "10:05"` rather than
  the exact interval (the exact-padding math is pinned independently by
  `test_gap_after_a_neighbour`).

## Findings tally
Raised ~11 (across both iterations), accepted 6 (fixed 6 — 1 P2 + 5 P3), rejected 0,
P3-ignored 3 (accepted gaps above).

## Verification (final)
- `uv run pytest backend/tests/ -q` → **1226 passed**
- `uv run ruff check backend/` → **All checks passed!**
- `npm test -- SettingsPanels.test.ts` → **8 passed**; `npx vue-tsc --noEmit` → exit 0
