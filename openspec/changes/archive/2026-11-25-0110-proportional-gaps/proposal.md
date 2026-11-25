# 0110 — Proportional mid-day gaps in the Dark 4a timeline

## Why

Feature 0106 capped every free gap in the Dark 4a stack layout at 60 px so the day would fit without scrolling. A 70-minute gap and a 170-minute gap then looked the same, and the owner could no longer see how much free time the day had. See [docs/features/0110_PLAN.md](../../../docs/features/0110_PLAN.md).

## What changes

- A free gap between two blocks renders on the true scale again (170 minutes = 340 px at 2 px/min), with hour labels inside it.
- Gaps touching the window start or end, the merged trailing gap on today, an empty day and spacers stay capped at the edge-stub height.
- Blocks keep the 28 px floor and the compact row.

## Capabilities

- `frontend/schedule-page`: MODIFIED "Dark 4a stack layout", "Dark 4a gap row" (test rename).
- `frontend/undo-and-drag`: MODIFIED "Drag cancellation and frozen geometry" (scenario wording and test renames).

## Impact

Dark 4a timeline geometry only. The day no longer fits the column without scrolling. No backend, API or migration change; other themes keep the linear layout.
