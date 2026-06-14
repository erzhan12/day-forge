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
- Pure helper `computeRenderBounds(blocks)` exported from
  `frontend/src/utils/scheduleTime.ts`; `Schedule.vue` calls it for its
  `renderBounds` computed. Input blocks must match the same visibility
  filter and day-window clamps `displayList` uses (`Schedule.vue:247–248,
  260, 298–299`): keep only blocks overlapping `[DAY_START_MINUTES,
  DAY_END_MINUTES)`, then clamp edge anchors with `Math.max(…,
  DAY_START_MINUTES)` / `Math.min(…, DAY_END_MINUTES)`. Extract a shared
  `filterVisibleBlocks(blocks)` if needed so both paths stay in sync.
  After filtering, sort by `(start_time, sort_order)` (same tie-break as
  `useDrag` / `findCurrentBlock`) before picking first/last visible blocks —
  do not rely on caller array order.
  - `renderBounds` in `Schedule.vue` is computed from **real** blocks
    (`props.blocks`), never preview blocks.
  - Return shape is always `{ renderStart: number; renderEnd: number }`.
  - No visible blocks (empty day): `{ renderStart: DAY_START_MINUTES,
    renderEnd: DAY_END_MINUTES }` — full-day gap unchanged.
  - Leading gap > `STUB_MINUTES`: `renderStart = firstBlockStart −
    STUB_MINUTES`; otherwise `DAY_START_MINUTES` (natural render).
  - Trailing gap > `STUB_MINUTES`: `renderEnd = lastBlockEnd +
    STUB_MINUTES`; otherwise `DAY_END_MINUTES`.
- **Linear geometry invariant (flow layout):** `displayList` stacks items
  vertically (`Schedule.vue:446–498`); block Y-offset equals the sum of
  preceding `itemHeight` values. Ghost drag uses absolute `top` from the
  same origin (`useDrag` `ghostTop`). Both must agree:
  `(blockStart − activeRenderStart) × PX_PER_MINUTE`. Mid-day gaps keep
  `render_minutes = duration_minutes`; only the two edge gaps may compress.
  `STUB_MINUTES` is the compression **threshold** and the **anchor offset**
  (`renderStart = firstBlockStart − STUB_MINUTES`), not a fixed rendered
  height during drag.
- **Freeze during drag:** `useDrag` owns a single reactive snapshot
  (`frozenRenderBounds`, see **Frozen-bounds contract** below) set in
  `startDrag` from the render-bounds getter (`props.blocks`) and cleared in
  `endDrag` / `cancelDrag`. Both px↔minute math and `Schedule.vue`
  `displayList` edge-gap compression read that one snapshot while
  `isDragging` — the layout cannot re-anchor mid-drag. After drop, manual
  add/edit/delete, undo restore, or AI chat mutations, `renderBounds`
  recomputes from live blocks — adding a block earlier than the current
  first block automatically re-anchors the stub to the new first block.

## Component changes

### `frontend/src/pages/Schedule.vue`

- Destructure `frozenRenderBounds` from `useDrag` (alongside `isDragging`).
  Pass a render-bounds getter `() => computeRenderBounds(props.blocks)` as a
  new `useDrag` option — see **Frozen-bounds contract**; do not snapshot
  bounds locally in `Schedule.vue`.
- `displayList`: leading/trailing gap items keep their full semantic range
  (`start_time: "06:00"`, `end_time: <firstStart>`) and gain `compact: true`
  when compressed. **Rendered height is derived, not fixed:**
  - `activeRenderStart` / `activeRenderEnd` = frozen bounds while
    `isDragging`, else live `renderBounds`.
  - Leading (compressed): `render_minutes = max(0, firstStart −
    activeRenderStart)` where `firstStart` comes from `effectiveBlocks`
    (preview positions during drag).
  - Trailing (compressed): `render_minutes = max(0, activeRenderEnd −
    lastEnd)` where `lastEnd` comes from `effectiveBlocks`.
  - At rest with computed bounds, leading/trailing formulas evaluate to
    `STUB_MINUTES` by construction; during drag they grow/shrink so flow
    layout stays aligned with `ghostTop`.
- `itemHeight` uses `item.render_minutes ?? item.duration_minutes`.
- `nowOffsetPercent` unchanged: a now-line inside a stub compresses
  proportionally into the rendered stub height (approximate position
  accepted).
- Rendered leading-gap height clamps `Math.max(0, …)` against the frozen
  origin (see **Drag edge cases** below).

### Frozen-bounds contract (single owner: `useDrag`)

- **Owner:** `frontend/src/composables/useDrag.ts` exports reactive
  `frozenRenderBounds: Ref<{ renderStart: number; renderEnd: number } | null>`.
- **Lifecycle:** `startDrag` calls the render-bounds getter once (wired from
  `Schedule.vue` to `computeRenderBounds(props.blocks)`), assigns the
  result to `frozenRenderBounds`, then runs px math against those values.
  `endDrag`, `cancelDrag`, and `resetState` set `frozenRenderBounds` to
  `null`. No second snapshot in `Schedule.vue`.
- **Consumers (same ref, same timing):**
  1. `useDrag` — px↔minute origin, lower clamp, grab-time `blockTopPx`,
     `ghostTop = containerPaddingTop + (newStart − frozenRenderStart) ×
     PX_PER_MINUTE`.
  2. `Schedule.vue` `displayList` — when `isDragging.value &&
     frozenRenderBounds.value`, edge-gap `render_minutes` uses
     `frozenRenderBounds` as `activeRenderStart` / `activeRenderEnd` in the
     linear formulas above (preview `firstStart` / `lastEnd` from
     `effectiveBlocks`); otherwise uses live `renderBounds`. Flow-cumulative
     height of the leading gap must equal `(previewFirstStart −
     frozenRenderStart) × PX_PER_MINUTE` so the preview `TimeBlock` slot and
     ghost stay co-located.
- **Source blocks:** getter always reads **real** `props.blocks`, never
  `effectiveBlocks` / preview state — preview may move the first block
  earlier without re-anchoring the stub until drop.

### Drag edge cases

- **Layout during drag:** `displayList` walks `effectiveBlocks` (preview +
  shift ghosts). Edge-gap **anchors** (`activeRenderStart` /
  `activeRenderEnd`) are frozen from `props.blocks` at `startDrag`; edge-gap
  **extent** (`firstStart` / `lastEnd`) follows preview positions.
- **First block moves later (e.g. 09:00 → 10:00, frozen renderStart
  08:30):** leading `render_minutes = 10:00 − 08:30 = 90` (180px); ghost
  at 180px — flow layout and ghost stay aligned. Do **not** pin stub height
  at `STUB_MINUTES` during drag.
- **First block moves earlier toward frozen origin:** leading
  `render_minutes = max(0, previewFirstStart − frozenRenderStart)` shrinks;
  at `previewFirstStart === frozenRenderStart` the leading gap omits or
  renders 0px. `useDrag` lower clamp (`frozenRenderStart`) prevents times
  below the frozen origin until drop re-anchors.
- **Trailing gap:** mirror with `render_minutes = max(0, frozenRenderEnd −
  previewLastEnd)`.

### `frontend/src/composables/useDrag.ts`

- Options gain a render-bounds getter
  `() => { renderStart: number; renderEnd: number }`. Export
  `frozenRenderBounds` (reactive ref, see **Frozen-bounds contract**).
  `startDrag` sets it from the getter; `endDrag` / `cancelDrag` /
  `resetState` clear it. Px math reads `frozenRenderBounds.value` (or
  destructures once at drag start — values are immutable for the drag
  duration). **Do not** replace every `DAY_START_MINUTES` /
  `DAY_END_MINUTES` reference with snapshot values — pixel origin and
  semantic validity are separate:
  - **Px↔minute origin** (`updatePreview` lines 271–286, `startDrag` line
    359): use frozen `renderStart` as the zero px anchor —
    `newStart = frozenRenderStart + snapped`;
    `ghostTop = containerPaddingTop + (newStart − frozenRenderStart) ×
    PX_PER_MINUTE`; `blockTopPx = (startMinutes − frozenRenderStart) ×
    PX_PER_MINUTE` at grab time.
  - **Lower clamp:** `frozenRenderStart` (not `DAY_START_MINUTES`).
  - **Upper clamp:** `DAY_END_MINUTES − blockDuration` — semantic day
    validity unchanged; `resolveConflicts` still gates on
    `DAY_END_MINUTES` (line 132).
  - **No `renderEnd` upper clamp** for drop times — cursor-reachable range
    is naturally bounded by container height ≈ `(renderEnd − renderStart) ×
    PX_PER_MINUTE`; add a defensive `renderEnd − blockDuration` guard only
    if manual testing shows off-by-one at the bottom edge.
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

- **Vitest — `computeRenderBounds` matrix** in
  `frontend/tests/scheduleTime.test.ts` (pure function, no component mount):
  leading only, trailing only, both, gap ≤ `STUB_MINUTES` (no
  compression), empty day (unchanged), first block exactly at 06:00 / last
  block exactly at 23:00, block entirely outside 06:00–23:00 (filtered
  out), block partially outside (clamped anchors).
- **Vitest — GapSlot:** compact variant label, hint, full-range emit.
- **Vitest — useDrag:** lower clamp at frozen `renderStart`, upper clamp
  still at `DAY_END_MINUTES`, ghost math with shifted origin,
  `frozenRenderBounds` set on `startDrag` and cleared on `endDrag` /
  `cancelDrag`, existing drag tests updated for the render-bounds getter.
- **Vitest — `displayList` geometry (Schedule.vue or extracted
  `buildDisplayList` helper):** with frozen bounds active
  (`renderStart = 08:30`, `renderEnd` frozen) and preview first block at
  10:00, assert leading-gap `render_minutes === 90` and cumulative offset to
  the preview block equals `ghostTop` formula `(10:00 − 08:30) ×
  PX_PER_MINUTE`; mirror for trailing last-block move. This catches
  flow-vs-ghost divergence that isolated `useDrag` unit tests miss.
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
