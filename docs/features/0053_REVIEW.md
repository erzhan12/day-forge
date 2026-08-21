# 0053 — Review trail (issue #110, configurable day window)

## External code review (codex gpt-5.6-sol + cursor agent)

Read-only external engines; every finding verified against source before accept/reject.
All fixes applied locally, uncommitted. Verification after each fix round.

### Iteration 1 — raised 1 P1 + 8 P2 + several P3

Backend logic verified correct end-to-end (single `ScheduleWindow` source; AI reject
incl. symmetric bound; clamp/skip 422 contract; changed-boundary-only PATCH;
metadata-only edits; window resolved once per request incl. under the AI apply lock).
**Frontend Phase-2B (slices 7-8) shipped materially incomplete for custom windows.**

Accepted + fixed:
- **P1** `useDrag.ts` drop-clamp + `resolveConflicts` cascade hardcoded to 23:00 →
  threaded the prop window (`getWindow` 9th arg from `Schedule.vue`; `dayEndMinutes`
  passed to `resolveConflicts`).
- **P2** No inert spacer — out-of-window→window region emitted a clickable `gap` →
  added a non-interactive `spacer` display-item type + non-clickable render.
- **P2** 422 `outside_window` skip never consumed → `AddBlockForm.vue` /
  `AddToScheduleDialog.vue` now branch on `code === "outside_window"` before the
  `errors` flatten, show a window-derived "Skipped — outside your day window HH:MM–HH:MM"
  notice, push no undo.
- **P2** `AddToScheduleDialog` warning + `outsideVisibleHours` hardcoded 06:00–23:00 →
  window-derived via a new `:window` prop from `Schedule.vue`.
- **P2/P3** `filterVisibleBlocks` `.sort()` mutated the Inertia `props.blocks` array →
  `[...blocks].sort()`.
- **P2** Empty window-overlapping subset unioned raw window bounds → based render
  extents on the window-overlapping subset (no in-window blow-out).
- **P2** Model `clean()` ignored seconds/microseconds (`06:00:30` passed, breaking
  HH:MM alignment) → rejects non-zero seconds/microseconds via shared
  `check_time_on_grid`.
- **P2** `validate_window` `strptime("%H:%M")` accepted non-canonical `6:0` → strict
  `^\d{2}:\d{2}$` guard.
- **P2** Missing tests → added scheduleTime custom-window/spacer, `CategoryBreakdown`
  span, `AddBlockForm`/`AddToScheduleDialog` skip UX, prompt-render-embeds-bounds,
  template custom-window.

Rejected:
- **P2 (codex)** "Lock the `UserScheduleSettings` row across AI apply." The plan
  intentionally resolves the window under the schedule/user apply transaction
  (`ai/views.py:585,625`); the residual read-committed race is sub-millisecond and
  benign, and holding the settings row across the LLM call is strictly worse.

Also fixed a **real regression the missing tests caught**: `mark_reviewed_if_active`
was orphaned into `UserScheduleSettings` during the model insertion (broke 9
analytics/status tests) — moved back onto `Schedule`.

Verification after iter-1 fixes: backend 1029 passed, ruff clean; frontend 818
passed, vue-tsc clean.

### Iteration 2 — all iter-1 fixes verified MATCH; new findings were narrow edge cases

Accepted + fixed (both genuine render bugs in the new out-of-window spacer geometry):
- **P2** `spliceNowMarker` retagged a `spacer` as `block-with-now` (which has no
  `block`) when *now* fell inside it → rendered nothing, dropping the spacer height
  and hiding the NowLine. Fixed: `spliceNowMarker` leaves `spacer` items untouched
  (the pre-window zone is outside the working day, so no marker).
- **P2** All-outside day (e.g. a `06:00–07:00`-only day narrowed to `08:00`) sized the
  canvas to the blocks alone → 0px working window. Fixed: base the render extents on
  the working window, then union the stranded blocks. Regression tests added.

Residual (handed to the user — narrow, only affect a narrowed window with stranded
legacy blocks):
- **P2/P3** Trailing out-of-window region between an in-window block and a *late*
  legacy block is still emitted as a clickable `gap` (the plan specified only the
  *leading* spacer).
- **P2 (codex, contested)** Drop lower-clamp uses union `renderStart` rather than
  `window.startMinutes`, so a drop preview can land before the window start when a
  legacy block sits earlier. Deferred deliberately: `renderStart` also carries the
  feature-0026 off-grid from-event contract, so changing it risks a 0026 regression
  and needs its own test pass.
- **P3** `useDrag.test.ts` doesn't pass `getWindow` (production `Schedule.vue` is
  wired); stale display-clamp comments in `useDrag.ts`.

Stop rationale: convergence guard — severity collapsed from the whole interaction
layer (iter 1) to narrow out-of-window-geometry edges (iter 2); the two render-breaking
edges are fixed and tested, the residuals are uncommon-path refinements.

Final verification: backend 1029 passed, ruff clean; frontend 820 passed, vue-tsc clean.

### Iterations 3–5 (residual close-out, at user request)

The user chose to close the deferred residuals before shipping. Fixed + regression-tested:
- **Trailing out-of-window spacer** (`pushInterBlockGap` now carves lead-spacer /
  in-window-gap-capped-at-window-end / trailing-spacer).
- **Drag drop window-start floor** applied AFTER the day-end clamp (`useDrag.ts`), so a
  block longer than the window can't preview before the window start.
- **Late-only leading gap** capped at `window.end` + overflow spacer
  (`buildBaseDisplayItems`).
- **Early-only trailing remainder** before a lone out-of-window block emitted as an
  inert spacer; clickable trailing gap starts at `window.start`.

Out-of-window regions on every side (leading, inter-block lead/trail, trailing,
all-outside, early-only) are now inert spacers, never clickable "add here" gaps.

Rejected (documented tradeoffs, not defects):
- **Too-long-block drop overflow** — a block longer than the entire window cannot fit;
  the preview pins to the window start and the end overflows, which the backend
  clamp/skip contract already handles. Cursor confirmed this is the intended tradeoff.
- **Mid-drag preview row-shift (codex-only, iter 5)** — actively dragging a lone
  stranded out-of-window block into the window can transiently shift preview rows vs the
  ghost because `activeRenderStart` stays frozen mid-drag. Transient, self-corrects on
  drop, and only in a narrowed-window + lone-stranded-legacy-block + active-drag corner.
  Deferred under the convergence guard: cursor returned NO P1/P2 for iterations 4 and 5
  while codex escalated one progressively narrower symmetric corner per round.

Stop: convergence guard — cursor clean two consecutive rounds; the sole remaining
codex item is a transient mid-drag cosmetic in a triple-nested edge.

Final verification: backend 1029 passed, ruff clean; frontend 825 passed, vue-tsc clean.
