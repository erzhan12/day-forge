# Feature 0017 — Code Review: Compact Timeline Edge Stubs

**Reviewed:** current working tree vs `docs/features/0017_compact_timeline_stubs_SPEC.md`  
**Review date:** 2026-06-14  
**Verification:** `npm test` in `frontend/` (`336` passed), `npx vue-tsc --noEmit` (clean)

## Verdict

Approve. No blocking or non-blocking correctness findings remain from this pass.

The compact timeline implementation now matches the approved geometry model:

- `computeRenderBounds` filters/clamps/sorts visible blocks before choosing dynamic render bounds.
- `buildBaseDisplayItems` derives compact edge-gap state from active render bounds, so drag layout and ghost math share the frozen origin.
- `useDrag` owns `frozenRenderBounds`, uses frozen `renderStart` for px↔minute math and lower clamp, and keeps the semantic upper clamp at `DAY_END_MINUTES`.
- `spliceNowMarker` preserves `render_minutes` and `compact`, so a compact edge stub remains compact when converted to `gap-with-now`.
- `GapSlot` keeps the full semantic range and emits that range on click while rendering the compact hint.

## Resolved From Prior Reviews

- Frozen-vs-live bounds divergence: fixed by removing the live bounds argument from `buildBaseDisplayItems`; compactness now follows `activeRenderStart` / `activeRenderEnd`.
- Trailing geometry parity: covered by a mirrored pixel-alignment assertion.
- Active-bounds compactness regression: covered for both leading and trailing gaps.
- Now-marker proportional math: covered by `nowOffsetPercent` tests.
- Compact `gap-with-now` preservation: covered by `spliceNowMarker` tests that assert `render_minutes` and `compact` survive the splice.

## Test Review

- `computeRenderBounds`: covers empty day, leading/trailing/both compression, threshold behavior, day edges, out-of-window filtering, and partial clamp/sort.
- `buildBaseDisplayItems`: covers leading/trailing drag geometry, pixel alignment, and active-bounds compactness.
- `spliceNowMarker`: covers off-today no-op, compact edge gap to `gap-with-now`, preserved compact geometry fields, block `with-now`, and single insertion.
- `nowOffsetPercent`: covers off-today, proportional compact-stub placement, and zero-span guard.
- `GapSlot`: covers compact hints, label, CSS class, and full semantic `add-here` emit.
- `useDrag`: covers frozen-bounds lifecycle, shifted origin, lower clamp, and existing drag concurrency safeguards.

No snake_case/camelCase or nested payload mismatches were found. The feature remains frontend-only and consistently uses `start_time`, `end_time`, and `sort_order`.

## Note

`Schedule.vue` still has a local `DisplayItem` interface that mirrors `ScheduleDisplayItem` from `scheduleTime.ts`; this is harmless, but the duplicate type can be consolidated later if the display-list helpers continue to grow.
