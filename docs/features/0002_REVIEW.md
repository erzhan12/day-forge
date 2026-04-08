# Phase 2 Review

## Findings

No functional regressions found in the current implementation.

## Notes

- The previous finding about content-driven heights for short durations is resolved. `Schedule.vue` now uses fixed duration-scaled slot heights instead of `min-height`.
- The previous finding about the now line disappearing at 23:59 is resolved. The trailing synthetic gap now reaches `"24:00"`, so the final minute is still covered by a containing interval.
- The previous finding about gap-mode overlays adding extra non-time height is resolved. Active gaps now use the same absolute-overlay approach as active blocks.
- The previous finding about the schedule not using a real time axis is resolved. `Schedule.vue` now applies duration-based slot heights and uses overlays for both active blocks and active gaps.
- The previous finding about midpoint-based placement inside active blocks is resolved.
- The previous finding about toggle/delete failures in `TimeBlock.vue` is resolved. The component now awaits both actions and surfaces inline error feedback on failure.
- The previous zero-length trailing-gap failure is resolved. `GapSlot.vue` now suppresses add-here emission when a valid interval cannot be produced after clamping.
- The previous fallback-overlap issue is resolved. `GapSlot.vue` no longer back-shifts the start time outside the clicked gap.
- The earlier fixes around CSRF, JSON mutation transport, non-UTC date helpers, malformed PATCH validation, and login/mutation CSRF coverage still hold.
- `backend/schedules/views.py` still returns 400 for an invalid `schedule/<date>/` path, while the plan specified 404.
- Re-review completed after the latest frontend adjustments; no remaining behavioral regressions were reproduced in the reviewed code paths.
- I still do not see any project frontend test files covering now-line behavior or mutation UI flows.

## Checks Run

- `uv run pytest backend/tests/ -q` -> 46 passed
- `uv run ruff check backend/` -> passed
- `npx vue-tsc --noEmit` -> passed
- `npm run build` -> passed
- Code-path review of `frontend/src/pages/Schedule.vue`, `frontend/src/components/AddBlockForm.vue`, `frontend/src/components/GapSlot.vue`, `frontend/src/components/TimeBlock.vue`, `frontend/src/components/NowLine.vue`, and `backend/schedules/api.py`
