# Lessons Learned

Patterns and corrections discovered during development. Review at session start.

## Live AI comparisons need intent-based expectations and independent state

Recorded completions test how the server handles a particular model reply. Their
expected questions are not gold answers for a live model: `add Gym` permits an
automatic add under the current contract. Replaying `18:00` after the live model
has already added Gym creates a different conversation from the recorded fixture.

Use independent canonical states when comparing one heuristic. Freeze existing
blocks, IDs, clock, and prior transcript for each arm and repetition. Score actual
schedule changes against authorized titles, explicitly requested fields, and
preserved neighbours. Accept declared cosmetic naming variants. Keep parse failures,
wrong fields, missed actions, and unauthorized additions as separate measurements.
Retain the runner and raw evidence; a passing evaluation runner means the experiment
completed, not that every live response met its expectation.

## Preserving data in a controller also requires preserving it in the panel

R08 kept the last successful Todoist/Habitica rows during a failed background refresh, but the panel's `v-if="error"` / `v-else` hid the list. Render the error banner independently of retained rows. Empty failures still show only the error. Test this at both controller and component boundaries.

## Disconnect must invalidate optimistic mutations, not only resource reads

Clearing tasks after a disconnected resource response does not stop a pending completion POST from restoring its removed row on failure. Advance the shared resource epoch and abort mutations when accepting disconnect. A late account read, GET or rollback must not re-establish the previous source.

## Keep destructive-action confirmations inside the page

The in-app browser stalled on `window.confirm` during the R04 block deletion test and required a manual click. Use a DOM dialog for block deletion so browser automation can confirm or cancel it. Preserve keyboard access, focus restoration, and Undo. Stop dialog key events from reaching page shortcuts, and dismiss pending confirmation if its block, date, or mutation state changes.

## Copy reactive snapshots into plain values

Inertia and Vue props can be reactive proxies. `structuredClone` on those proxies throws `DataCloneError`. `useUndo.snapshotBlocks()` copies flat block rows with `map(block => ({ ...block }))`; `useScheduleRevision` owns the canonical snapshot. For nested data, unwrap or copy the relevant values explicitly. Copying a snapshot does not make its revision current.

## Concurrent mutations during drag-and-drop require snapshot validation

When a drag holds state across async boundaries (pointer down → pointer up), concurrent mutations (AI chat, undo, manual edits, cross-tab writes) can land while the operation is in flight. If the drop handler diffs preview state against a drag-start snapshot without validating that snapshot is still current, externally-moved neighbours appear "changed" and get written back at stale coordinates — silent data clobber.

Detect this before applying updates: compare live blocks to the drag-start snapshot (excluding the dragged block). Check ID-set equality first (catches additions/deletions), then verify each neighbour's `start_time`, `end_time`, and `sort_order`. If diverged, abort the operation without posting.

`useDrag.blocksExternallyMutated` guards `endDrag`. The page controller's mutation phase also blocks new drags during AI or reconciliation. Keep both checks when moving ownership between composables.

## A "plan-mandated divergence" still needs its boundary conditions checked

The old Todoist loader treated every non-503 result as proof of a connected account, including a network failure with no HTTP status. That promoted a disconnected source after a failed request. R08 replaces that inference with explicit `meta.account_state` and `meta.resource_state` in `useDatedResource`; a bare status still cannot establish account existence.

When reviewing a plan-approved exception, test its missing precondition as well as its successful path. Include network/parse failures and unrelated authentication failures when mapping a provider result to account state.

## Update fixtures when removing a compatibility default

R12 removed invented frontend category rows after confirming that authenticated page loaders bootstrap a live catalog. Leaf and PiP fixtures that omitted categories then exercised the new error path instead of their intended behavior. Pass a complete realistic catalog with one sink and one new-block default; keep separate malformed-catalog tests. Do not weaken an unrelated UI assertion to accommodate an incomplete fixture.
