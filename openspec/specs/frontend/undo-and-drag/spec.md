# frontend/undo-and-drag Specification

## Purpose
Client behavior of the Schedule page's Undo history and drag-to-move. It covers when an accepted write enters the date-scoped Undo stack, how a restore sends the entry's historical revision and provenance proofs, how a successful restore rebinds only the directly preceding entry, when history is invalidated, the keyboard and toolbar entry points, and how a drag computes, validates and commits a reorder from a frozen snapshot.

## Requirements

### Requirement: Undo registration requires confirmed metadata
The page SHALL record an Undo entry only for an accepted write that changed blocks and carries confirmed previous and expected revisions for the date, revision and scope currently shown; otherwise it SHALL record nothing.
Enforced: frontend/src/composables/useMutationUndo.ts::registerMutationUndo, frontend/src/composables/useUndo.ts::useUndo

#### Scenario: No-op or unconfirmed success
- **WHEN** a write succeeds without a change or without accepted metadata
- **THEN** no Undo entry is created

Tests: frontend/tests/useBlockCompletion.test.ts::useBlockCompletion::does not create undo for a no-op or success without accepted metadata, frontend/tests/useScheduleRevision.test.ts::historical undo chain::rejects actions with missing historical revision instead of filling it from the current page

#### Scenario: Write resolves after navigation
- **WHEN** a block edit resolves after the user moved to another date
- **THEN** its history is not recorded on the new date

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::ignores stale toggle history after date navigation, frontend/tests/TimeBlock.test.ts::TimeBlock::ignores stale edit history after date navigation

#### Scenario: Failed write
- **WHEN** a block update fails
- **THEN** no Undo entry is pushed

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::pushUndo NOT called on failed update

### Requirement: Undo stack and toast
The Undo stack SHALL keep at most 20 entries, dropping the oldest; a non-silent entry SHALL show an actionable toast for 8 seconds, while silent entries (block edits, completion, drag, chat apply, event import) SHALL show no toast.
Enforced: frontend/src/composables/useUndo.ts::useUndo

#### Scenario: Stack overflow
- **WHEN** a 21st entry is pushed
- **THEN** the oldest entry is dropped

Tests: frontend/tests/useUndo.test.ts::useUndo::enforces max 20 stack size

#### Scenario: Toast lifetime
- **WHEN** a non-silent entry is pushed
- **THEN** its toast disappears after 8 seconds or on dismiss

Tests: frontend/tests/useUndo.test.ts::useUndo::toast auto-dismisses after 8 seconds, frontend/tests/useUndo.test.ts::useUndo::dismissToast clears toast immediately, frontend/tests/useUndo.test.ts::useUndo::new push clears previous toast timer

#### Scenario: Silent entry
- **WHEN** a silent entry is pushed
- **THEN** it is on the stack but no toast appears

Tests: frontend/tests/useUndo.test.ts::useUndo::silent action is pushed to stack but shows no toast (issue #54)

### Requirement: Undo is scoped to the viewed date
Undo SHALL restore the most recent entry for the date on screen, ignoring entries for other dates, and SHALL show `Nothing to undo.` when that date has none.
Enforced: frontend/src/composables/useUndo.ts::findLastIndexForDate

#### Scenario: Later entry for another date
- **WHEN** the top entry belongs to another date
- **THEN** the current date's latest entry is undone

Tests: frontend/tests/useUndo.test.ts::useUndo::undoes the current date's entry even when a later date sits on top, frontend/tests/useUndo.test.ts::useUndo::performUndo is a no-op when top action targets a different date

#### Scenario: Empty for this date
- **WHEN** no entry exists for the viewed date
- **THEN** the toast reads `Nothing to undo.`

Tests: frontend/tests/useUndo.test.ts::useUndo::performUndo on empty stack shows 'Nothing to undo' toast

### Requirement: Restore sends historical state
Undo SHALL POST the entry's previous blocks, including original IDs and `restore_proof`, with the entry's own expected revision, and SHALL NOT retry a mismatched restore against the latest revision.
Enforced: frontend/src/composables/useUndo.ts::useUndo, frontend/src/composables/useSchedule.ts::useSchedule

#### Scenario: Restore payload
- **WHEN** the user undoes an entry
- **THEN** the restore request carries the stored blocks and proofs

Tests: frontend/tests/useUndo.test.ts::useUndo::sends correct payload to restoreBlocks, frontend/tests/useUndo.test.ts::useUndo::keeps authenticated provenance with each historical block through consecutive Undo

#### Scenario: Historical revision mismatch
- **WHEN** the entry's expected revision is no longer current
- **THEN** the restore is treated as a conflict and not resent with the latest revision

Tests: frontend/tests/useScheduleRevision.test.ts::historical undo chain::does not retry a historical restore against the latest revision

### Requirement: Successful restore rebinds only a contiguous predecessor
After a successful restore the entry SHALL be removed; the preceding entry for that date SHALL take the new revision only if its expected revision equals the undone entry's previous revision, otherwise that date's history SHALL be cleared.
Enforced: frontend/src/composables/useUndo.ts::useUndo

#### Scenario: Contiguous chain
- **WHEN** A then B are undone in order
- **THEN** each restore sends its historical revision and A is rebased after B's undo

Tests: frontend/tests/useScheduleRevision.test.ts::historical undo chain::sends historical expected_revision and rebases only the contiguous A→B→undo B→undo A chain

#### Scenario: Navigation during restore
- **WHEN** the user navigates away while a restore is in flight
- **THEN** the entry is removed but no toast appears on the new date

Tests: frontend/tests/useUndo.test.ts::useUndo::removes the entry but shows no toast when navigating away mid-restore, frontend/tests/useUndo.test.ts::useUndo::removes the intended entry when a new action shifts a full stack mid-flight

#### Scenario: AI undo
- **WHEN** an AI chat entry is undone
- **THEN** the most recent applied-result chip is cleared

Tests: frontend/tests/useChat.test.ts::useChat::clears only the most recent applied chip on AI undo

### Requirement: Failed restore
A failed restore on the same date SHALL clear that date's history for `schedule_changed`, a missing status or a 5xx result and keep the entry for any other failure; `schedule_changed` SHALL show its review message and other failures `Undo failed. Please try again.`
Enforced: frontend/src/composables/useUndo.ts::useUndo

#### Scenario: Ordinary failure
- **WHEN** the restore fails with an ordinary 4xx error
- **THEN** the entry stays on the stack and the failure toast is shown

Tests: frontend/tests/useUndo.test.ts::useUndo::performUndo keeps action on failure

#### Scenario: Schedule changed
- **WHEN** the restore returns `schedule_changed`
- **THEN** the date's history is cleared and `Schedule changed. Review the refreshed schedule before undoing.` is shown

### Requirement: History invalidation
The page SHALL clear a date's history on an external revision, a conflict or an unknown write outcome for it, and SHALL clear all history on a user or session reset while keeping other dates' entries on date navigation.
Enforced: frontend/src/composables/useUndo.ts::useUndo, frontend/src/composables/useScheduleRevision.ts::createScheduleRevision

#### Scenario: Unknown outcome
- **WHEN** a write outcome is unknown even if the fresh GET shows the same revision
- **THEN** that date's history is cleared

Tests: frontend/tests/useScheduleRevision.test.ts::historical undo chain::invalidates history on unknown write result even when fresh GET has the same revision

#### Scenario: Session cleanup
- **WHEN** the user or session resets
- **THEN** history for all dates is cleared

Tests: frontend/tests/useScheduleRevision.test.ts::historical undo chain::clears all dates' history on user/session cleanup

#### Scenario: Return to a date
- **WHEN** the user navigates away and back
- **THEN** the earlier date's entry can still be undone

Tests: frontend/tests/useUndo.test.ts::useUndo::performUndo restores when navigating back to the action's date

### Requirement: Undo entry points
Cmd+Z or Ctrl+Z outside form fields and the toolbar Undo button SHALL trigger Undo; both SHALL do nothing while mutations are disabled or busy, and a second Undo SHALL be ignored while one is in flight.
Enforced: frontend/src/composables/useUndo.ts::useUndo, frontend/src/pages/Schedule.vue::performUndo

#### Scenario: Disabled schedule
- **WHEN** the shortcut is pressed while mutations are disabled
- **THEN** nothing is sent

Tests: frontend/tests/useUndo.test.ts::useUndo::keyboard shortcut Ctrl+Z is blocked while schedule mutations are disabled, frontend/tests/useUndo.test.ts::useUndo::performUndo is a no-op while schedule mutations are disabled

#### Scenario: Concurrent Undo
- **WHEN** Undo is triggered again during a restore
- **THEN** the second call is ignored

Tests: frontend/tests/useUndo.test.ts::useUndo::performUndo ignores concurrent calls while restore is in flight

#### Scenario: Toolbar button
- **WHEN** a silent entry exists and no write is busy
- **THEN** the Undo button is enabled, and it is disabled while another write is in flight

Tests: frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::offers button Undo for silent mutations without requiring a keyboard, frontend/tests/Schedule.test.ts::Schedule.vue auto-draft watcher::disables button Undo while another schedule write is in flight

### Requirement: Drag conflict resolution
A drag preview SHALL pin the dragged block at the drop time, push overlapping later blocks forward in cascade with off-grid durations rounded up to the snap grid, reassign sort_order, and mark the drop invalid if the cascade passes the user's day-window end.
Enforced: frontend/src/composables/useDrag.ts::resolveConflicts, frontend/src/composables/useDrag.ts::roundUpDuration

#### Scenario: Overlap cascade
- **WHEN** a block is dropped onto neighbours
- **THEN** each overlapping neighbour shifts after the previous one

Tests: frontend/tests/useDrag.test.ts::resolveConflicts::single block shifts forward on overlap, frontend/tests/useDrag.test.ts::resolveConflicts::cascade through multiple blocks

#### Scenario: Past the window end
- **WHEN** the cascade would end after the window end
- **THEN** no resolution is produced and the drop is invalid

Tests: frontend/tests/useDrag.test.ts::resolveConflicts::returns null when cascade exceeds DAY_END

#### Scenario: Off-grid neighbour
- **WHEN** a displaced neighbour has an off-grid duration
- **THEN** its duration is rounded up to the grid

Tests: frontend/tests/useDrag.test.ts::resolveConflicts off-grid neighbours (feature 0026)::rounds a displaced off-grid neighbour's duration up to the grid

### Requirement: Drag drop validation
On drop the client SHALL send nothing when the date or drag context changed, the schedule became disabled, or any other block's ID set, start, end or sort_order differs from the drag-start snapshot.
Enforced: frontend/src/composables/useDrag.ts::blocksExternallyMutated, frontend/src/composables/useDrag.ts::useDrag

#### Scenario: Neighbour changed
- **WHEN** another block moved during the drag
- **THEN** the drop is aborted

Tests: frontend/tests/useDrag.test.ts::useDrag.endDrag (undo snapshot)::aborts drop when a non-dragged block changed during the drag, frontend/tests/useDrag.test.ts::blocksExternallyMutated::returns true when a neighbour's times changed

#### Scenario: Date or disabled
- **WHEN** the date changed or the schedule became disabled during the gesture
- **THEN** the drop is cancelled

Tests: frontend/tests/useDrag.test.ts::useDrag.endDrag (undo snapshot)::cancels drop when the active date changed during the gesture, frontend/tests/useDrag.test.ts::useDrag.endDrag (undo snapshot)::cancels drop if the schedule became disabled while the gesture was held

### Requirement: Drag commit
A valid drop SHALL POST a reorder containing only blocks whose time or order changed, send nothing when none changed, and record a silent Undo entry from the controller's accepted snapshot.
Enforced: frontend/src/composables/useDrag.ts::useDrag

#### Scenario: Pre-drag snapshot
- **WHEN** a drag commits
- **THEN** the Undo entry holds the pre-drag blocks

Tests: frontend/tests/useDrag.test.ts::useDrag.endDrag (undo snapshot)::pushes pre-drag blocks (not [], not the post-reset snapshot) into the undo action

#### Scenario: Two drags
- **WHEN** a second drag starts before the first reorder resolves
- **THEN** the first Undo entry keeps its own snapshot

Tests: frontend/tests/useDrag.test.ts::useDrag.endDrag (undo snapshot)::first drag's undo keeps its own snapshot when a second drag starts mid-await, frontend/tests/useDrag.test.ts::useDrag.endDrag (undo snapshot)::uses the latest date source when pushing drag undo

### Requirement: Drag cancellation and frozen geometry
A drag SHALL freeze render bounds, the now marker and the day window at start, clamp the preview to the window, and be cancelled without a write by Escape, viewport resize, a context change or unmount.
Enforced: frontend/src/composables/useDrag.ts::useDrag

#### Scenario: Unmount mid-drag
- **WHEN** the component unmounts during a drag
- **THEN** the gesture is cancelled without committing

Tests: frontend/tests/useDrag.test.ts::useDrag lifecycle::cancels an active gesture on component unmount without committing or leaving listeners

#### Scenario: Frozen state
- **WHEN** a drag starts and ends
- **THEN** frozen bounds and now are set and then cleared

Tests: frontend/tests/useDrag.test.ts::useDrag frozen render bounds::sets frozenRenderBounds on startDrag and clears on endDrag, frontend/tests/useDrag.test.ts::useDrag frozen render bounds::sets frozenNowMinutes from getNow on startDrag and clears on endDrag

#### Scenario: Narrowed window
- **WHEN** the day window starts later than the default
- **THEN** the preview never starts before the window start

Tests: frontend/tests/useDrag.test.ts::useDrag off-grid geometry and payload (feature 0026)::clamps the drop preview to the window start under a narrowed window (feature 0053)
