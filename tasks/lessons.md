# Lessons Learned

Patterns and corrections discovered during development. Review at session start.

## `structuredClone` on Vue reactive / Inertia props throws `DataCloneError`

Inertia page props (and Vue `defineProps` results) are wrapped in a readonly reactive proxy. `structuredClone` can't clone these — it fails with `DataCloneError: [object Array] could not be cloned`.

When cloning for a snapshot (e.g. undo stack), unwrap the proxy first. For flat objects, `arr.map(x => ({ ...x }))` is the simplest. For nested data, `JSON.parse(JSON.stringify(x))` or `toRaw()` + manual walk.

Seen at `frontend/src/composables/useUndo.ts:65` — AddBlockForm submit crashed the native event handler because `snapshotBlocks()` cloned `props.blocks` directly.
