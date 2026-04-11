# Phase 3 Review

## Findings

No findings.

## Notes

- The previous undo-toast finding is resolved. `useUndo()` marks success/failure confirmation toasts as non-actionable, `Schedule.vue` passes that flag through, and `UndoToast.vue` hides the Undo button when `actionable` is false.
- The previous drag finding remains resolved. `resolveConflicts()` keeps the dragged block anchored at the snapped drop time, and `frontend/tests/useDrag.test.ts` covers dragging onto an earlier block.
- The previous malformed API payload findings are resolved. Reorder and restore now reject non-object top-level JSON bodies, non-object nested entries, and reorder requests with missing/non-integer IDs.
- The backend reorder and restore endpoints otherwise match the planned all-or-nothing behavior for authenticated, same-schedule, non-overlapping updates in the reviewed code paths.
- The implementation includes the expected frontend pieces: `useDrag`, `useUndo`, `UndoToast`, shared schedule-time helpers, drag handle UI, ghost preview, and undo integration across add/edit/toggle/delete/drag mutation sites.
- Test coverage now includes backend reorder/restore validation, malformed top-level and nested payloads, `useSchedule`, conflict-resolution basics and upward-overlap anchoring, undo stack behavior, actionable/non-actionable toast rendering, add-block undo, and time-block mutation undo.
- `.Codex/rules/` is referenced by `AGENTS.md` but is not present in this checkout; I used `RULES.md`, `tasks/lessons.md`, the plan, and the implementation instead.

## Checks Run

- `uv run pytest backend/tests/ -v` -> 96 passed, 70 warnings
- `uv run ruff check backend/` -> passed
- `npm run test -- --run` -> 61 passed
- `npx vue-tsc --noEmit` -> passed
- `git diff --check` -> passed
