# frontend/schedule-page Specification

## Purpose
Client behavior of the Schedule page's canonical writer. It covers how the page owns one revisioned snapshot of blocks and status, how every schedule write captures and settles against that snapshot, how the app-root write coordinator gates a returning page, scope resets on date, zone, user and session changes, the catalog lockout, date navigation, automatic and manual draft generation, block completion and title or delete edits. Undo and drag live in `frontend/undo-and-drag`.

## Requirements

### Requirement: Writes carry the captured revision and user
Every schedule write SHALL send the captured snapshot's revision as `expected_revision` and the captured user ID in the `X-Schedule-User` header, without reading the browser time zone.
Enforced: frontend/src/composables/useSchedule.ts::useSchedule, frontend/src/composables/useHttp.ts::requestJson

#### Scenario: Draft write
- **WHEN** the page generates a draft
- **THEN** the request carries the captured revision and account identity

Tests: frontend/tests/useDraft.test.ts::useDraft::binds draft writes to the captured account identity, frontend/tests/useDraft.test.ts::useDraft::sends the expected revision and never reads the browser timezone

#### Scenario: Reorder write
- **WHEN** the page reorders blocks
- **THEN** the body carries the updates with the expected revision

Tests: frontend/tests/useSchedule.test.ts::useSchedule::sends reorderBlocks with correct payload

### Requirement: Single page writer
The page SHALL allow one schedule write at a time and, while a write or reconciliation is in progress, SHALL reject a new write with `schedule_synchronizing` and `Schedule is updating. Wait for it to finish, then try again.`
Enforced: frontend/src/composables/useScheduleRevision.ts::createScheduleRevision, frontend/src/composables/useScheduleRevision.ts::scheduleCaptureFailure

#### Scenario: Second write while pending
- **WHEN** a write is started while another is pending
- **THEN** the second write is refused without a request

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::permits only one page writer while the request is pending, frontend/tests/useChat.test.ts::useChat::blocks another turn while the first request owns the schedule

### Requirement: Atomic acceptance of complete responses
The page SHALL replace its blocks, status and revision from a response only when it names the captured date with a valid matching revision and complete blocks; a response without blocks SHALL be accepted only at the unchanged captured revision.
Enforced: frontend/src/composables/useScheduleRevision.ts::createScheduleRevision

#### Scenario: Ask or no-op response
- **WHEN** a successful response keeps the captured revision and omits blocks
- **THEN** the known snapshot is retained and the mutation is marked unchanged

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::retains a no-op/ask snapshot and marks it unchanged

#### Scenario: Follow-up uses accepted snapshot
- **WHEN** a second write follows an accepted response without a page reload
- **THEN** it uses the accepted snapshot and revision

Tests: frontend/tests/useChat.test.ts::useChat::uses the accepted canonical snapshot and revision for a follow-up without reload

### Requirement: Revision never regresses
The page SHALL ignore Inertia props with a lower revision or for another date, SHALL keep a newer accepted snapshot over same-revision props, and SHALL treat a higher props revision as an external change that invalidates Undo history.
Enforced: frontend/src/composables/useScheduleRevision.ts::createScheduleRevision

#### Scenario: Older props arrive
- **WHEN** props with an older revision arrive after an accepted response
- **THEN** canonical blocks are unchanged

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::does not regress canonical blocks when older props arrive

#### Scenario: External revision
- **WHEN** props arrive with a higher revision than the page knows
- **THEN** history for that date is cleared rather than rebased

Tests: frontend/tests/useScheduleRevision.test.ts::historical undo chain::clears old history on a new external revision instead of rebasing from GET

### Requirement: Conflict and unknown outcomes reconcile
A `409 schedule_changed` or `pending_intent_stale`, or an unknown outcome (no status, 5xx, or a non-ok status below 300), SHALL invalidate history and hold the writer while one partial Inertia reload runs; the write SHALL NOT be retried.
Enforced: frontend/src/composables/useScheduleRevision.ts::isScheduleRevisionConflict, frontend/src/composables/useScheduleRevision.ts::refreshSchedule

#### Scenario: Conflict
- **WHEN** a write returns `409 schedule_changed`
- **THEN** the writer stays busy until the reload callbacks finish and the POST is not repeated

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::holds the conflict lease until reload callbacks finish and never retries the POST

#### Scenario: Unknown outcome
- **WHEN** a write fails without a definite status
- **THEN** the page reconciles once and stays busy until the reload completes

Tests: frontend/tests/useChat.test.ts::useChat::reconciles an unknown outcome once and keeps the writer busy until reload completes, frontend/tests/useScheduleRevision.test.ts::historical undo chain::invalidates history on unknown write result even when fresh GET has the same revision

### Requirement: Confirmed success with an unusable body
A successful write whose body cannot be accepted SHALL remain a success, SHALL reload the schedule, SHALL report `schedule_reconciled` or `schedule_sync_failed` with a refresh message, and SHALL NOT produce Undo metadata.
Enforced: frontend/src/composables/useScheduleRevision.ts::createScheduleRevision

#### Scenario: Fallback reload fails
- **WHEN** a confirmed success cannot be installed and the reload fails
- **THEN** the result stays ok with `Saved, but the schedule could not be refreshed. Refresh before making another change.`

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::keeps confirmed POST success distinct from failed fallback reload

#### Scenario: No history from a fallback GET
- **WHEN** the snapshot was refreshed by a fallback GET
- **THEN** no Undo metadata is produced from that revision

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::does not create historical undo metadata from a fallback GET revision, frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::does not label a later external revision as the accepted operation after auxiliary reload

### Requirement: Invalid session ends the page scope
A 401 or `session_invalid` result, including a redirect to the login page, SHALL clear the page's canonical state, history and write coordinator and reject further writes, unless the response belongs to a departed user scope.
Enforced: frontend/src/composables/useHttp.ts::requestJson, frontend/src/composables/useScheduleRevision.ts::createScheduleRevision

#### Scenario: Session expires during a write
- **WHEN** a current write returns `session_invalid`
- **THEN** canonical state is cleared and later writes are rejected

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::clears canonical state and rejects writes on invalid session or logout

#### Scenario: Old user's 401
- **WHEN** a 401 arrives for a write made by the previous user
- **THEN** the new user's page is not cleared

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::discards old-user 401 responses without clearing the new user's page

### Requirement: Date and user scope isolation
A date or user change SHALL start a new page scope so late responses from the old scope cannot update it; a user change SHALL wait for the new user's schedule props before bootstrapping.
Enforced: frontend/src/composables/useScheduleRevision.ts::createScheduleRevision

#### Scenario: Navigate away and back
- **WHEN** a response for a departed scope arrives after navigating away and back
- **THEN** it does not update the current page

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::isolates late responses even after navigating away and back

#### Scenario: New user's props
- **WHEN** the auth user changes before the new schedule object arrives
- **THEN** the old schedule is not adopted for the new user

Tests: frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::quarantines auth-only props until the new user's schedule object arrives, frontend/tests/useScheduleRevision.test.ts::canonical schedule mutation owner::batches separately replaced auth and schedule props before bootstrapping the new user

### Requirement: Time zone change reconciles the day
When the saved zone changes on the same date and user, the page SHALL wait for that day's pending writes, then reload, and SHALL keep writes closed until that reload is accepted.
Enforced: frontend/src/composables/useScheduleRevision.ts::createScheduleRevision

#### Scenario: Pending write during zone change
- **WHEN** the zone changes while a write is pending
- **THEN** the reload starts after the write settles and the gate holds until it is accepted

Tests: frontend/tests/useScheduleRevision.test.ts::timezone context reconciliation::waits for an old write before reading and keeps the gate until that read is accepted

#### Scenario: Reload fails
- **WHEN** the zone reload fails
- **THEN** the gate stays closed until a new date bootstraps

Tests: frontend/tests/useScheduleRevision.test.ts::timezone context reconciliation::keeps the context gate on read failure but lets a new date bootstrap, frontend/tests/useScheduleRevision.test.ts::timezone context reconciliation::invalidates the first context read across an A-B-A switch

### Requirement: Write coordinator gates a returning page
An app-root coordinator SHALL record pending writes, the highest accepted revision and uncertain outcomes per user and date, and a page returning to that scope SHALL stay closed until old writes settle and a reload reaches that revision.
Enforced: frontend/src/composables/scheduleWriteCoordinator.ts::createScheduleWriteCoordinator

#### Scenario: Late commit after return
- **WHEN** a page remounts on a day whose earlier write is still pending
- **THEN** it waits and reloads that day after the write commits

Tests: frontend/tests/useScheduleRevision.test.ts::app-root write handoff::holds remounted A after an old return GET and reloads A after the late commit, frontend/tests/useScheduleRevision.test.ts::app-root write handoff::retains the accepted revision floor when the POST settles before a stale navigation GET remounts A

#### Scenario: Reload below the floor
- **WHEN** the reconciliation read returns a revision below the accepted one
- **THEN** the writer stays gated

Tests: frontend/tests/useScheduleRevision.test.ts::app-root write handoff::keeps the writer gated when a nominally successful reconciliation still returns below the accepted revision, frontend/tests/useScheduleRevision.test.ts::app-root write handoff::keeps a remounted writer closed when fresh props arrive before handoff reload finishes

#### Scenario: Rejected old write
- **WHEN** the old write is definitely rejected
- **THEN** the remounted writer is released

Tests: frontend/tests/useScheduleRevision.test.ts::app-root write handoff::releases a remounted writer after a definitely rejected old write

#### Scenario: Auxiliary fields
- **WHEN** a write that asked for extra reload fields settles after its page left
- **THEN** the returning page's reload includes those fields

Tests: frontend/tests/useScheduleRevision.test.ts::app-root write handoff::includes auxiliary review fields when an Analytics write settles after its owner departed

### Requirement: Coordinator clears on account boundaries
The coordinator SHALL clear all records on Login, a null user or a user change, and on a page's session or user reset, ignoring settlements from the cleared epoch; a disposed page SHALL NOT clear it.
Enforced: frontend/src/composables/scheduleWriteCoordinator.ts::provideScheduleWriteCoordinator

#### Scenario: Old session tickets
- **WHEN** a write from a cleared session settles
- **THEN** a later same-user page does not inherit its gate

Tests: frontend/tests/useScheduleRevision.test.ts::app-root write handoff::drops old session tickets so a later same-user page cannot inherit them

#### Scenario: Disposed owner
- **WHEN** an old page unmounts after another account signed in
- **THEN** the newer account's coordinator is not cleared

Tests: frontend/tests/useScheduleRevision.test.ts::app-root write handoff::does not let a disposed owner clear a newer account's root coordinator, frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::scopes pending schedule writes to the current root session

### Requirement: Invalid category catalog locks the page
When the category catalog is absent or malformed the page SHALL show `Category data could not be loaded.` with a reload link instead of schedule controls, SHALL block writes, keyboard Undo and auto-draft, and SHALL cancel an active drag.
Enforced: frontend/src/pages/Schedule.vue::categoryCatalogValid

#### Scenario: Empty catalog
- **WHEN** the page loads with an empty catalog
- **THEN** a reload error replaces the schedule controls

Tests: frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::shows a reload error instead of schedule controls for an empty catalog

#### Scenario: Catalog breaks mid-session
- **WHEN** a partial reload makes a valid catalog invalid
- **THEN** an active drag is cancelled and keyboard Undo is blocked

Tests: frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::cancels an active drag when a partial reload corrupts the catalog, frontend/tests/useSchedulePageController.test.ts::useSchedulePageController::blocks keyboard Undo after a valid page becomes mutation-disabled

### Requirement: Date navigation
The date navigator SHALL move one civil day back or forward, offer `Today` only when the viewed date is not today in the saved zone, and navigation SHALL dismiss the Undo toast and abandon page-scoped chat and draft state.
Enforced: frontend/src/components/DateNavigator.vue::offsetDate, frontend/src/composables/useSchedulePageController.ts::useSchedulePageController

#### Scenario: DST boundary
- **WHEN** the user steps across a daylight-saving change
- **THEN** the date moves by exactly one civil day

Tests: frontend/tests/DateNavigator.test.ts::DateNavigator::moves one civil day across DST boundaries, frontend/tests/DateNavigator.test.ts::DateNavigator::uses the saved-zone today supplied by the page

#### Scenario: Navigate to another date
- **WHEN** the page date changes
- **THEN** the toast is dismissed and AI state for the old date is cleared

Tests: frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::dismisses undo toast when navigating to another date, frontend/tests/useSchedulePageController.test.ts::useSchedulePageController::provides mutation context and clears page-scoped AI state on navigation and logout

### Requirement: Automatic draft once per date
The page SHALL request a draft automatically when `auto_draft_pending` is true, the catalog is valid and the canonical day has no blocks, at most once per date for the same user.
Enforced: frontend/src/composables/useSchedulePageController.ts::useSchedulePageController

#### Scenario: First visit
- **WHEN** the page mounts with the signal and no blocks
- **THEN** one draft request is sent

Tests: frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::(a) fires generateDraft once on first mount when auto_draft_pending=true and blocks are empty

#### Scenario: Non-empty day or no signal
- **WHEN** the day has blocks or the signal is false
- **THEN** no draft is requested

Tests: frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::does NOT fire when blocks are non-empty even with auto_draft_pending=true, frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::does NOT fire when auto_draft_pending=false on mount

#### Scenario: Same date emptied again
- **WHEN** blocks are later cleared on the same date
- **THEN** the draft is not requested again, while a new date gets its own attempt

Tests: frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::(c) does NOT refire after a partial reload populates blocks then clears them on the same date, frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::(b) fires for each new date when navigating with the same component instance

### Requirement: Draft request outcomes
Draft generation SHALL POST to the draft endpoint through the page writer, register Undo only for a confirmed changed diff, and show fixed copy for 422, 429 and 503, the schedule-changed message for a conflict, or the server error with `Draft generation failed` as fallback.
Enforced: frontend/src/composables/useDraft.ts::useDraft

#### Scenario: Accepted draft
- **WHEN** the draft is accepted with a changed diff
- **THEN** an Undo entry is recorded with the returned revision

Tests: frontend/tests/useDraft.test.ts::useDraft::records undo from the accepted draft diff with its expected revision, frontend/tests/useDraft.test.ts::useDraft::a successful no-op draft does not create undo

#### Scenario: Rejected draft
- **WHEN** the server rejects the draft
- **THEN** the error is shown without Undo and cleared on retry

Tests: frontend/tests/useDraft.test.ts::useDraft::shows the rejected block and window without creating Undo and clears the error on retry, frontend/tests/useDraft.test.ts::useDraft fallback-literal guard::generateDraft surfaces the exact fallback literal on an empty errors map

### Requirement: Abandoned draft responses
Navigation or a session reset SHALL drop the draft spinner and ignore the late response's error and Undo, while the write itself still settles through the page writer.
Enforced: frontend/src/composables/useDraft.ts::useDraft

#### Scenario: Navigate during a draft
- **WHEN** the user navigates before the draft resolves
- **THEN** the spinner clears and no Undo or error is recorded from it

Tests: frontend/tests/useDraft.test.ts::useDraft::abandonInFlight clears spinner and stale-completes without reload, frontend/tests/useDraft.test.ts::useDraft::stale in-flight draft does not set lastDraftError from a failed response, frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::does not push draft undo after navigating away before the request resolves

#### Scenario: Session ends
- **WHEN** the session ends during a draft
- **THEN** draft errors clear and the old response is ignored

Tests: frontend/tests/useDraft.test.ts::useDraft::clears draft errors and invalidates an old response when the session ends

### Requirement: Regenerate draft control
The Regenerate draft button SHALL be disabled without a template for the day's slot, while a draft is generating, while chat is processing, or while AI is marked unhealthy.
Enforced: frontend/src/components/RegenerateDraftButton.vue::disabled

#### Scenario: Chat busy
- **WHEN** a chat turn is processing
- **THEN** the button is disabled and emits nothing on click

Tests: frontend/tests/RegenerateDraftButton.test.ts::RegenerateDraftButton::disables while chat is processing, frontend/tests/RegenerateDraftButton.test.ts::RegenerateDraftButton::does not emit click while chat is processing

#### Scenario: AI unhealthy
- **WHEN** chat reports AI unhealthy
- **THEN** the button is disabled

Tests: frontend/tests/RegenerateDraftButton.test.ts::RegenerateDraftButton::disables when chat reports AI unhealthy

### Requirement: Serialized block completion
Each row SHALL send completion toggles one at a time with the block identity captured when the toggle begins, SHALL drop unsent toggles after a failed or uncertain result or a row reset, and SHALL refuse new toggles while the schedule is disabled.
Enforced: frontend/src/composables/useBlockCompletion.ts::useBlockCompletion

#### Scenario: Rapid toggles
- **WHEN** the user toggles twice quickly
- **THEN** the second PATCH waits for the first and both confirmed changes enter history

Tests: frontend/tests/useBlockCompletion.test.ts::useBlockCompletion::serializes rapid intents and preserves both confirmed operations in history, frontend/tests/useBlockCompletion.test.ts::useBlockCompletion::captures the original identity before mutable block props change

#### Scenario: Conflict mid-queue
- **WHEN** the first toggle conflicts
- **THEN** the queued toggle is cancelled and the reconciled value is shown

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::cancels a queued toggle after conflict and shows the reconciled block

#### Scenario: Disabled schedule
- **WHEN** the schedule is disabled
- **THEN** a new toggle is refused

Tests: frontend/tests/useBlockCompletion.test.ts::useBlockCompletion::rejects new completion when disabled and clears errors after a later accepted request, frontend/tests/TimeBlock.test.ts::TimeBlock::disables the checkbox while the schedule is disabled

### Requirement: Optimistic completion checkbox
The checkbox SHALL show the latest requested value immediately, SHALL keep it against older reloads while saving, and on failure SHALL show the canonical value with `Failed to update` without retrying.
Enforced: frontend/src/components/TimeBlock.vue::toggleCompleted

#### Scenario: Click
- **WHEN** the user clicks the checkbox
- **THEN** it flips before the PATCH resolves

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::checkbox flips immediately on click before PATCH resolves, frontend/tests/TimeBlock.test.ts::TimeBlock::does not clobber a newer optimistic value when an older reload lands mid-flight

#### Scenario: Rejected toggle
- **WHEN** the PATCH is rejected
- **THEN** the spinner ends and nothing is retried

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::settles a rejected response without retrying or leaving the spinner

#### Scenario: Row reused
- **WHEN** the row is reset to another block or date while a write is accepted
- **THEN** its UI resets without aborting the accepted write

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::resets reused row UI without aborting an accepted write

### Requirement: Block title edit
Clicking a title SHALL open an editor; Enter or blur SHALL save a changed trimmed title once, Escape SHALL cancel, an unchanged title SHALL not be sent, and a failure SHALL reopen the editor with `Failed to update title`.
Enforced: frontend/src/components/TimeBlock.vue::saveTitle

#### Scenario: Save on Enter
- **WHEN** the user edits the title and presses Enter
- **THEN** one PATCH is sent and the editor closes

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::saves title on enter and exits edit mode, frontend/tests/TimeBlock.test.ts::TimeBlock::does not double-save when blur fires after enter

#### Scenario: Escape or unchanged
- **WHEN** the user presses Escape or leaves the title unchanged
- **THEN** nothing is sent

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::cancels editing on escape without saving, frontend/tests/TimeBlock.test.ts::TimeBlock::does not save if title unchanged

#### Scenario: Failed save
- **WHEN** the PATCH fails
- **THEN** an error is shown

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::shows error on failed title update

### Requirement: Block delete confirmation
Deleting a block SHALL require the shared confirmation dialog, submit once, close the dialog when its target changes or another write is busy, and on failure show `Failed to delete` without Undo.
Enforced: frontend/src/components/TimeBlock.vue::handleDelete

#### Scenario: Confirmed delete
- **WHEN** the user confirms deletion
- **THEN** one DELETE is sent even if confirmation repeats before render

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::calls delete after confirm, frontend/tests/TimeBlock.test.ts::TimeBlock::submits only once if confirmation is repeated before the next render

#### Scenario: Busy schedule
- **WHEN** another write becomes busy while confirmation is open
- **THEN** the confirmation is dismissed and deletion disabled

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::dismisses confirmation and disables deletion while another write is busy

#### Scenario: Failed delete
- **WHEN** the DELETE fails
- **THEN** an error is shown and no Undo is recorded

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::shows deletion failure without recording Undo
