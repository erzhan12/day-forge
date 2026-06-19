# Lessons Learned

Patterns and corrections discovered during development. Review at session start.

## `structuredClone` on Vue reactive / Inertia props throws `DataCloneError`

Inertia page props (and Vue `defineProps` results) are wrapped in a readonly reactive proxy. `structuredClone` can't clone these — it fails with `DataCloneError: [object Array] could not be cloned`.

When cloning for a snapshot (e.g. undo stack), unwrap the proxy first. For flat objects, `arr.map(x => ({ ...x }))` is the simplest. For nested data, `JSON.parse(JSON.stringify(x))` or `toRaw()` + manual walk.

Seen at `frontend/src/composables/useUndo.ts:65` — AddBlockForm submit crashed the native event handler because `snapshotBlocks()` cloned `props.blocks` directly.

## Concurrent mutations during drag-and-drop require snapshot validation

When a drag holds state across async boundaries (pointer down → pointer up), concurrent mutations (AI chat, undo, manual edits, cross-tab writes) can land while the operation is in flight. If the drop handler diffs preview state against a drag-start snapshot without validating that snapshot is still current, externally-moved neighbours appear "changed" and get written back at stale coordinates — silent data clobber.

Detect this before applying updates: compare live blocks to the drag-start snapshot (excluding the dragged block). Check ID-set equality first (catches additions/deletions), then verify each neighbour's `start_time`, `end_time`, and `sort_order`. If diverged, abort the operation without posting.

Seen at `frontend/src/composables/useDrag.ts` — `blocksExternallyMutated` guards `endDrag`. Defense in depth: `scheduleDisabled` also prevents new drags from starting while `isChatProcessing` is true.

## A "plan-mandated divergence" still needs its boundary conditions checked

When code intentionally diverges from a precedent (documented + plan-blessed), adversarial reviewers tend to wave it through as "matches the plan" and never drill into its edge cases. That is a blind spot.

Feature 0020 (`useTodoist.ts`): the plan said "on any non-503 error (401/500/502/504) set `connected = true`" because a real HTTP status proves the account row exists. The impl coded this as an `else` branch — which also swallows the `result.status === undefined` case (`useHttp.requestJson` returns `{ok:false, errors}` with **no status** on network/parse failure, `useHttp.ts:67-70`). So a pure network failure for a *disconnected* user elevated `connected` and showed the panel. Two adversarial review passes missed it; an external review caught it.

Rule: when reviewing an intentional divergence, enumerate its stated precondition (here: "a definitive HTTP status exists") and test the path where that precondition is **false**. Fix: gate the elevation on `result.status !== undefined`, and always add a test for the no-status / network-failure branch whenever a composable maps HTTP status to UI state.
