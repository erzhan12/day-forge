# Feature 0017 — Compact Timeline Edge Stubs (Spec)

**Status:** Approved design, pre-plan.
**Date:** 2026-06-11
**Scope:** Frontend only — no backend, API, or schema changes.

## Problem

When the first block of a day starts well after `DAY_START` (06:00), the
schedule timeline renders a full-height leading `GapSlot` from 06:00 to the
first block (`frontend/src/pages/Schedule.vue:259-268`) at
`PX_PER_MINUTE = 2` (`frontend/src/utils/scheduleTime.ts:8`). A 09:00 first
block produces 360px of dead space above any content; the user must scroll
past it every visit. The trailing gap (last block → 23:00) has the same
problem at the bottom.

## Decision summary

Collapse the leading and trailing edge gaps to fixed-height compact stubs
("Approach A — origin-shift linear render"). The timeline remains strictly
linear in minutes, but its rendered origin and terminus become dynamic.
Mid-day gaps are unchanged. Approved by user 2026-06-11; alternatives
rejected: piecewise px↔minute mapping (nonlinear stub region, highest
regression risk on drag code), expand-on-drag (mid-drag layout jump),
configurable `DAY_START` preference (doesn't fix the dynamic case, needs
backend).

## Geometry model

- New constant `STUB_MINUTES = 30` in `frontend/src/utils/scheduleTime.ts`.
  Stub rendered height = `STUB_MINUTES × PX_PER_MINUTE` = 60px.
- `renderBounds` computed in `Schedule.vue` from **real** blocks
  (`props.blocks`), never preview blocks:
  - No visible blocks (empty day): `{start: DAY_START_MINUTES,
    end: DAY_END_MINUTES}` — full-day gap unchanged.
  - Leading gap > `STUB_MINUTES`: `renderStart = firstBlockStart −
    STUB_MINUTES`; otherwise `DAY_START_MINUTES` (natural render).
  - Trailing gap > `STUB_MINUTES`: `renderEnd = lastBlockEnd +
    STUB_MINUTES`; otherwise `DAY_END_MINUTES`.
- Block rendered position stays linear: `(start − renderStart) ×
  PX_PER_MINUTE`. All existing slot stacking (heights from
  `duration_minutes`) is preserved; only the two edge-gap items render at a
  height different from their semantic duration.
- **Freeze during drag:** `renderBounds` is snapshotted into a ref when a
  drag starts and released when it ends, so the layout cannot re-anchor
  mid-drag. It recomputes reactively on drop, manual add/edit/delete, undo
  restore, and AI chat mutations — adding a block earlier than the current
  first block automatically re-anchors the stub to the new first block.

## Component changes

### `frontend/src/pages/Schedule.vue`

- `displayList`: leading/trailing gap items keep their full semantic range
  (`start_time: "06:00"`, `end_time: <firstStart>`) and gain
  `render_minutes: STUB_MINUTES` plus `compact: true` when compressed.
- `itemHeight` uses `item.render_minutes ?? item.duration_minutes`.
- `nowOffsetPercent` unchanged: a now-line inside a stub compresses
  proportionally into the 60px (approximate position accepted).
- Rendered leading-gap height clamps `Math.max(0, …)` against the frozen
  origin (see drag edge case below).

### `frontend/src/composables/useDrag.ts`

- Options gain a render-bounds getter. `startDrag` snapshots it into
  locals; the hardcoded `DAY_START_MINUTES` / `DAY_END_MINUTES` in the
  px↔minute conversions and clamps (`updatePreview` lines 271–286,
  `startDrag` line 359) switch to the snapshot values.
- `resolveConflicts` keeps the full 06:00–23:00 day window — shift chains
  may transiently push a neighbor block above the frozen `renderStart`.
  This is cosmetic-only ghost misalignment until drop re-anchors; accepted.

### `frontend/src/components/GapSlot.vue`

- New `compact?: boolean` prop: denser visual variant with an
  "earlier" / "later" hint so the compression is legible.
- Label keeps the full semantic range (e.g. "06:00 – 09:00", "Free — 3h").
- `add-here` emit unchanged — carries the full real range (so the add flow
  can still target 06:00 even when the stub renders 60px).

## Pinned semantics trade-off

Drag-drop into a stub maps only to the last `STUB_MINUTES` real minutes
adjacent to the edge block (e.g. 08:30–09:00 for a 09:00 first block).
Earlier times remain reachable via stub click (emits the full range) or AI
chat. Dropping at 08:30 re-anchors `renderStart` to 08:00 and the stub
relabels to "06:00 – 08:30". Same mirrored behavior for the trailing stub.

## Testing

- **Vitest — renderBounds matrix:** leading only, trailing only, both,
  gap ≤ `STUB_MINUTES` (no compression), empty day (unchanged), first
  block exactly at 06:00 / last block exactly at 23:00.
- **Vitest — GapSlot:** compact variant label, hint, full-range emit.
- **Vitest — useDrag:** clamps at `renderStart`/`renderEnd`, ghost math
  with shifted origin, bounds frozen across `startDrag`→`endDrag`,
  existing drag tests updated for the new options getter.
- **Vitest — now marker:** gap-with-now inside a stub renders
  proportionally.
- **Browser smoke (full dev stack):** both stubs visible on a 09:00–18:00
  day; stub click opens add flow with 06:00 range; drag into stub lands at
  ≥ `renderStart`; adding an earlier block (manual + AI chat) re-anchors
  the stub.

## Out of scope

- Mid-day gap compression.
- Configurable `DAY_START` user preference.
- Backend changes of any kind.

## Files touched

`frontend/src/utils/scheduleTime.ts`, `frontend/src/pages/Schedule.vue`,
`frontend/src/composables/useDrag.ts`,
`frontend/src/components/GapSlot.vue`, plus their test files.
