# Lessons Learned

Patterns and corrections discovered during development. Review at session start.

## Category confirmation and narrow settings layouts need browser checks

Block deletion already used a DOM dialog, but category deletion still called
native confirm. In CUA the click timed out and the dialog API returned no handle;
the category was later found deleted. Do not retry a destructive click without
checking its outcome. Share the DOM confirmation component and cover Cancel,
focus restoration, changed targets, and duplicate confirms. Category rows must
wrap: their original layout reached 459 px inside a 390 px viewport.

## Distinguish an advertised browser API from a completed native feature test

The in-app browser exposes Document PiP, but Show indicator did not produce an
open window even on a fresh visible page with native input. A Login transition
and passing cleanup unit tests cannot prove that an existing PiP window closed.
Keep that browser case open and record the concrete limitation.

## Silent Undo needs a visible control on touch screens

Suppressing mutation toasts left every Undo entry available only through a keyboard
shortcut. Expose the existing date-scoped `canUndo` and `performUndo` through the
page controller and render a persistent toolbar button. Gate it on the same mutation
state as keyboard Undo. Browser verification must include clicking it after an AI
write, deletion, and draft generation at a mobile viewport.

## Logout must invalidate Inertia history as well as client state

Clearing the session and page composables did not stop Back from rendering cached
private props. Enable Inertia history encryption and clear its key when rendering
Login, including after session expiry. Verify Back in a fresh tab after enabling
encryption; older plaintext history entries cannot be retroactively encrypted.
Restart a development server launched with `--noreload` before validating a changed
checkout. A six-day-old process produced a chat apply error that disappeared on
the current code after restart.

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
