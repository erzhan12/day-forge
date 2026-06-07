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
