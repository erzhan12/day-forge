# 0018 Code Review — Suppress undo toast for obvious in-UI edits

**Verdict: APPROVE — plan implemented exactly, no P0/P1 issues, tests green (98 passed). Clean.**

The `silent?: boolean` flag was added to `UndoAction`, gated in `pushUndo`, and applied to all five obvious-edit call sites (add/edit/toggle/delete/drag). The two keep-toast paths (`useChat.ts` `type:"ai"`, `Schedule.vue` `type:"draft"`) and `performUndo`'s own toasts were genuinely left untouched. New tests cover the silent-suppresses-toast, regression, and silent-then-performUndo cases; the five call-site tests assert `silent: true`.

---

## P0 — Critical

None.

## P1 — Major

None.

## P2 — Minor

None.

## P3 — Trivial nits

None.

---

## Verification notes (evidence for the verdict)

**1. Plan correctly implemented — every silent call site got it.**
- `frontend/src/components/AddBlockForm.vue:66` — `silent: true` on `type:"add"`. ✓
- `frontend/src/components/TimeBlock.vue:120` (`type:"edit"`), `:151` (`type:"toggle"`), `:173` (`type:"delete"`) — all three. ✓
- `frontend/src/composables/useDrag.ts:470` — `silent: true` on `type:"drag"`. ✓
- `frontend/src/types/index.ts:33` — `silent?: boolean` added, optional, `type` union untouched. ✓
- `frontend/src/composables/useUndo.ts:78` — gate is `if (!action.silent) { showToast(...) }`; stack push + `MAX_UNDO_STACK` shift stay unconditional. ✓

**2. Keep-toast paths genuinely intact (verified by grep + full read).**
- `useChat.ts:210-215` `type:"ai"` action object — no `silent` key. ✓
- `Schedule.vue:182-187` `type:"draft"` action object — no `silent` key. ✓
- `grep -rn "silent" frontend/src/` confirms the only functional `silent` occurrences are the 5 call sites + the type def + the `useUndo.ts` gate; all other hits are unrelated comments. ✓
- `performUndo` (`useUndo.ts:88,107,109`) calls `showToast(...)` directly for "Nothing to undo.", `Undone: …`, and "Undo failed. Please try again." — none route through `pushUndo`, so they remain visible regardless of the originating action's `silent` flag. ✓

**3. No data-alignment issues.** `silent` is a flat camelCase frontend-only flag; it is never serialized to the backend (`performUndo` builds `blocksPayload` from `previousBlocks` only, never spreads the action). No snake_case/shape mismatch surface.

**4. No bugs / no over-engineering.** Net change is ~one conditional plus one optional field. No file growth concern. The `silent` default-absent semantics ("absence means show toast") keep every pre-existing call site and test passing unchanged — confirmed by `useChat.test.ts:114` still asserting `toHaveBeenCalledOnce()` with no `silent` assertion.

**5. Style consistent.** Inline comments match the codebase's explanatory-comment convention (issue-number references, e.g. `(issue #54)`). No syntax mismatch.

**6. Tests — complete, isolated, fast, well-named.**
- `useUndo.test.ts:205` silent-suppresses-toast (happy): asserts `currentToast.value === null` AND `undoStack.length === 1` / `canUndo === true` (proves still undoable). ✓
- `useUndo.test.ts:214` non-silent regression: `silent:false` still toasts with `actionable:true`. ✓ (Note: covers the `silent:false` explicit branch; the pre-existing line-193 test covers the omitted-flag branch — both `undefined` and `false` are exercised.)
- `useUndo.test.ts:221` silent-then-performUndo: confirms `performUndo`'s `Undone: …` toast (`actionable:false`) fires independent of the action's `silent` flag. ✓
- Call-site assertions: `AddBlockForm.test.ts:118` (`silent:true` in add payload), `TimeBlock.test.ts:269/278/288` (edit/toggle/delete), `useDrag.test.ts:283` (`action.silent === true`). ✓
- Tests use existing `makeAction`/`mockPushUndo` patterns, proper mocking (`vi.mock` on `useSchedule`), fake timers, and per-test wrapper unmount cleanup. Ran in 1.20s — fast. ✓

**Test run:** `npx vitest run` over the 5 affected files — **98 passed (98)**, 0 failures.
