# schedules/revisions Specification

## Purpose
Defines how supported schedule writes are serialized, versioned and committed. Every manual block write (create, from-event create, PATCH, DELETE, reorder, restore) runs through one locking executor that checks the client's `expected_revision`, applies a whole command atomically, advances the day's revision at most once, and returns a snapshot captured inside the same transaction. Restore (Undo) authenticates block provenance through signed proofs, and the Schedule page GET shares the same per-user writer lock for first-use rows.

## Requirements

### Requirement: Expected revision validity
The system SHALL accept `expected_revision` only as a plain integer from 0 through 2**63-1. A missing value, a boolean, a string, a float, a negative or an oversized integer MUST be refused with `409` and code `schedule_changed` whose detail asks the client to refresh, and nothing is written.
Enforced: backend/schedules/mutations.py::parse_expected_revision, backend/schedules/mutations.py::_valid_revision, backend/schedules/mutations.py::MAX_REVISION

#### Scenario: Invalid revision value
- **WHEN** an otherwise valid manual write supplies `expected_revision` as `null`, `true`, `"0"`, `-1`, `0.0` or `2**100`
- **THEN** the response is `409` with `code: "schedule_changed"` and `errors.detail` containing "Refresh", and the schedule is unchanged

Tests: backend/tests/test_schedule_mutations.py::test_invalid_revision_requires_refresh, backend/tests/test_schedule_revisions.py::test_invalid_revision_is_controlled_conflict

#### Scenario: Every manual writer requires a revision
- **WHEN** an otherwise valid create, from-event create, PATCH, DELETE, reorder or restore request body omits `expected_revision`
- **THEN** the response is `409 schedule_changed`, the revision stays the same and no block is created, edited or removed

Tests: backend/tests/test_schedule_revisions.py::test_all_manual_writers_require_revision

### Requirement: Schedule conflict response shape
The system SHALL report revision conflicts as HTTP 409 with body `{"errors": {"detail": <message>}, "code": "schedule_changed"}`. A stale revision MUST use "Schedule changed. Refresh the page and try again."; a missing or invalid revision MUST use "Schedule version is missing or invalid. Refresh the page."
Enforced: backend/schedules/mutations.py::ScheduleChanged, backend/schedules/mutations.py::schedule_changed_response, backend/schedules/api.py::_mutation_errors

#### Scenario: Conflict raised inside a manual endpoint
- **WHEN** a manual block endpoint raises a schedule conflict
- **THEN** the endpoint returns the 409 `schedule_changed` envelope instead of an unhandled exception

Tests: backend/tests/test_schedule_revisions.py::test_all_manual_writers_reject_stale_revision

### Requirement: Stale revision rejection before mutation
The system MUST compare `expected_revision` with the locked schedule's current revision through a conditional update before running the write callback. A mismatch MUST raise a conflict without calling the callback, so no block, status or revision change is applied.
Enforced: backend/schedules/mutations.py::_execute, backend/schedules/mutations.py::execute_schedule_mutation

#### Scenario: Write against an older revision
- **WHEN** a schedule is at revision 1 and a write arrives with `expected_revision: 0`
- **THEN** the callback is never invoked, the response is `409 schedule_changed`, and the revision and blocks are unchanged

Tests: backend/tests/test_schedule_mutations.py::test_stale_request_never_calls_writer, backend/tests/test_schedule_revisions.py::test_all_manual_writers_reject_stale_revision

#### Scenario: Historical Undo after an intervening write
- **WHEN** a restore sends the revision of an earlier accepted write after another create, review or category deletion advanced the day
- **THEN** the restore returns `409 schedule_changed` and status, revision and blocks stay exactly as they were

Tests: backend/tests/test_undo_revisions.py::test_historical_undo_cannot_erase_an_intervening_write

#### Scenario: Two writers race on the same revision
- **WHEN** two independent SQLite connections submit writes with the same `expected_revision` concurrently
- **THEN** exactly one succeeds and the other receives a conflict, and the final revision is one higher than before

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_same_revision_has_one_winner_on_separate_sqlite_connections

### Requirement: Per-user write lock and lock order
The system SHALL start every supported schedule write by issuing an UPDATE on the owning User row (reserving the SQLite writer, row-locking on PostgreSQL), then lock the Schedule row and then its TimeBlock rows. If the User row does not exist the lock MUST raise `DoesNotExist`.
Enforced: backend/schedules/mutations.py::user_write_lock, backend/schedules/mutations.py::_execute

#### Scenario: Schedule locked before blocks
- **WHEN** a block PATCH or a reorder runs
- **THEN** `select_for_update` is applied to Schedule before TimeBlock

Tests: backend/tests/test_views.py::TestBlockDetail::test_non_time_patch_locks_parent_schedule_first, backend/tests/test_reorder.py::TestReorderBlocks::test_reorder_locks_schedule_before_children

#### Scenario: Writes on an empty day still lock the Schedule row
- **WHEN** a manual create or a restore runs on a day without blocks
- **THEN** the Schedule row is locked with `select_for_update`

Tests: backend/tests/test_views.py::TestCreateBlock::test_locks_schedule_row, backend/tests/test_restore.py::TestRestoreBlocks::test_locks_schedule_row

#### Scenario: Category deletion serializes with a schedule edit
- **WHEN** a category deletion and a manual edit of a block in that category run concurrently on separate connections
- **THEN** the two serialize under the User lock: either both apply (revision advances twice) or the edit is refused, and the block always ends in the sink category

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_category_delete_serializes_against_schedule_edit

### Requirement: Bounded SQLite busy retry
The system SHALL retry a whole write transaction up to three attempts when SQLite reports a locked or busy `OperationalError`, sleeping briefly between attempts, and MUST convert exhaustion into a `schedule_changed` conflict. Other `OperationalError`s and non-SQLite errors MUST propagate unchanged. Inside an enclosing atomic block only one attempt is made.
Enforced: backend/schedules/mutations.py::_retry_write, backend/schedules/mutations.py::run_user_maintenance

#### Scenario: Writer reservation held for every attempt
- **WHEN** another connection holds `BEGIN IMMEDIATE` for the whole schedule write
- **THEN** the User reservation is attempted exactly three times, the callback is never called, a conflict is raised and nothing is written

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_busy_retry_exhaustion_is_a_controlled_conflict_without_writes

#### Scenario: Policy writer busy once
- **WHEN** a schedule-settings PATCH, rule create or template create hits a locked error on its first save
- **THEN** the whole transaction is retried and succeeds with exactly one row; if every attempt is busy the response is `409 schedule_changed` and no row exists

Tests: backend/tests/test_policy_mutation_lock.py::test_policy_busy_write_retries_whole_transaction

#### Scenario: Busy error during block persistence
- **WHEN** saving a TimeBlock raises `OperationalError("database is locked")` on every attempt of a PATCH
- **THEN** the response is `409 schedule_changed` and the block and revision are unchanged

Tests: backend/tests/test_manual_command_contract.py::test_busy_persistence_write_uses_r04_conflict_mapping

### Requirement: Single revision bump per accepted change
The system SHALL advance a schedule's revision by exactly one, and refresh `updated_at`, when a write changes the day's status or any block's identity, title, times, category, completion, sort order or origin. A write that leaves status and blocks identical MUST keep the revision.
Enforced: backend/schedules/mutations.py::_execute, backend/schedules/mutations.py::_block_state

#### Scenario: Status-only change and repeated no-op
- **WHEN** a write promotes a draft day to active without touching blocks, and a later write at the new revision makes no change
- **THEN** the first advances the revision from 0 to 1 and the second keeps it at 1

Tests: backend/tests/test_schedule_mutations.py::test_noop_and_status_only_change

#### Scenario: Identical PATCH, reorder and restore
- **WHEN** PATCH sends an unchanged title, reorder sends unchanged times and sort order, and restore sends the current snapshot
- **THEN** each returns 200 with the same revision and the same block IDs

Tests: backend/tests/test_schedule_revisions.py::test_noop_patch_reorder_and_restore_do_not_bump_or_replace_ids

#### Scenario: Several changes in one write
- **WHEN** one accepted write creates a block and changes the status
- **THEN** the revision advances once, from 0 to 1

Tests: backend/tests/test_schedule_mutations.py::test_mutation_bumps_once_and_captures_committed_state

### Requirement: Atomic rollback of rejected writes
The system MUST roll back every block, status and revision change made by a write callback when the callback returns a response with status 400 or higher or raises an exception. A returned error response MUST be sent to the client unchanged.
Enforced: backend/schedules/mutations.py::MutationRejected, backend/schedules/mutations.py::_execute, backend/schedules/api.py::_mutation_errors

#### Scenario: Callback fails after writing
- **WHEN** a callback creates a block, promotes the status and then returns a 400 response or raises
- **THEN** the revision, status and blocks equal their state before the write

Tests: backend/tests/test_schedule_mutations.py::test_callback_failure_rolls_back_blocks_status_and_revision, backend/tests/test_schedule_revisions.py::test_status_failure_rolls_back_blocks_and_revision

### Requirement: First-day creation inside a versioned write
The system SHALL, when a schedule write targets a date with no Schedule, create the row only inside that write's transaction and only when `expected_revision` is 0. A non-zero or invalid revision MUST be refused as a conflict, and a rejected callback MUST roll the new row back.
Enforced: backend/schedules/mutations.py::_execute, backend/schedules/api.py::_create_block, backend/schedules/api.py::restore_blocks

#### Scenario: Stale first write on an absent day
- **WHEN** a write targets a date with no schedule using `expected_revision: 1`
- **THEN** a conflict is raised and no Schedule row exists

Tests: backend/tests/test_schedule_mutations.py::test_stale_first_day_creation_leaves_no_row

#### Scenario: Rejected first write
- **WHEN** a write at revision 0 on an absent day returns a 400 response
- **THEN** no Schedule row exists afterwards

Tests: backend/tests/test_schedule_mutations.py::test_rejected_first_day_creation_leaves_no_row

#### Scenario: Accepted first write
- **WHEN** a write at revision 0 on an absent day changes status or blocks
- **THEN** the schedule is created and returned at revision 1

Tests: backend/tests/test_schedule_mutations.py::test_first_day_creation_is_an_atomic_versioned_mutation, backend/tests/test_restore.py::TestRestoreBlocks::test_restore_creates_schedule_if_missing

### Requirement: Executor precondition and deferred revision
The system SHALL run an optional read-only precondition under the lock before the revision check. A non-error value it returns MUST complete the operation without a revision check or change; an error response MUST abort with rollback. A callable `expected_revision` MUST be resolved after the precondition and checked the same way.
Enforced: backend/schedules/mutations.py::execute_schedule_mutation, backend/schedules/mutations.py::_execute

#### Scenario: Idempotent precondition short-circuits
- **WHEN** the precondition returns a value for an already-reviewed day at revision 5 and the revision is a callable
- **THEN** neither the revision callable nor the write callback runs and the result reports revision 5 unchanged

Tests: backend/tests/test_schedule_mutations.py::test_idempotent_precondition_defers_revision_parse

### Requirement: Maintenance writes use the latest revision
The system SHALL let internal maintenance writers run under the same lock without an expected revision, applying the change to the current revision and advancing it once only if state changed. Category deletion MUST remap each affected day in ascending schedule ID order and leave unaffected days' revisions unchanged.
Enforced: backend/schedules/mutations.py::execute_schedule_maintenance, backend/schedules/categories.py::delete_category

#### Scenario: Maintenance on a day at revision 8
- **WHEN** a maintenance write promotes the status of a day at revision 8
- **THEN** the result is at revision 9

Tests: backend/tests/test_schedule_mutations.py::test_maintenance_explicitly_uses_latest_revision

#### Scenario: Category remap touches only affected days
- **WHEN** a category used on one day but not another is deleted
- **THEN** the affected day advances by one revision with its blocks moved to the sink, and the other day keeps its revision

Tests: backend/tests/test_schedule_mutations.py::test_category_remapping_bumps_only_affected_days

### Requirement: Response snapshot captured in the write transaction
The system SHALL return `schedule`, ordered `blocks` and `revision` serialized inside the accepted transaction. Create returns 201 and PATCH 200, each merged with the changed block's fields; DELETE returns 200 with `ok: true`; reorder and restore return the snapshot alone. A later write MUST NOT alter an earlier response.
Enforced: backend/schedules/mutations.py::_execute, backend/schedules/serialization.py::serialize_schedule_snapshot, backend/schedules/api.py::block_detail

#### Scenario: Another write commits right after
- **WHEN** a PATCH commits at revision 1 and a maintenance write commits revision 2 before the response is sent
- **THEN** the PATCH response still reports revision 1 and its own block title

Tests: backend/tests/test_schedule_revisions.py::test_response_snapshot_is_from_its_own_commit, backend/tests/test_schedule_mutations.py::test_mutation_bumps_once_and_captures_committed_state

### Requirement: Restore preserves day status
The system MUST NOT change a day's status when a restore is applied; promotion to active on forward edits is specified in schedules/blocks.
Enforced: backend/schedules/api.py::restore_blocks

#### Scenario: Restore keeps status
- **WHEN** a restore is applied to an active or a draft day
- **THEN** the day keeps its status

Tests: backend/tests/test_status_flow.py::TestRestoreDoesNotFlip::test_active_stays_active_on_restore, backend/tests/test_status_flow.py::TestRestoreDoesNotFlip::test_draft_stays_draft_on_empty_restore

### Requirement: Atomic multi-block reorder
The system SHALL apply all reorder updates as one command validated against the complete final candidate schedule, inside one locked transaction. All IDs MUST belong to one schedule of the user; a missing or foreign ID returns 404 and an invalid entry or final-state overlap returns 400, with no partial update.
Enforced: backend/schedules/api.py::reorder_blocks, backend/schedules/commands.py::ReorderCommand

#### Scenario: Swap two blocks
- **WHEN** one reorder request exchanges the positions of two adjacent blocks
- **THEN** both blocks move and the revision advances once

Tests: backend/tests/test_manual_command_contract.py::test_reorder_accepts_atomic_swap

#### Scenario: One entry would overlap
- **WHEN** one update in a batch overlaps an unchanged block
- **THEN** the response is 400 and the blocks are unchanged

Tests: backend/tests/test_reorder.py::TestReorderBlocks::test_overlap_with_unchanged_block_rejected

#### Scenario: One entry is invalid
- **WHEN** a batch contains one valid update and one with a malformed time
- **THEN** the response is 400 and the valid entry is not applied either

Tests: backend/tests/test_reorder.py::TestReorderBlocks::test_atomicity_no_partial_updates

#### Scenario: Blocks from different schedules or users
- **WHEN** the IDs span two schedules, or include another user's block
- **THEN** the response is 400 for mixed schedules and 404 for a foreign block

Tests: backend/tests/test_reorder.py::TestReorderBlocks::test_cross_schedule_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_cross_user_returns_404

### Requirement: Restore replaces the day's blocks as one snapshot
The system SHALL validate the complete restore list for shape, intervals and overlap, then replace all of the day's blocks with fresh rows. A snapshot identical to the current blocks, including origin, MUST write nothing and keep IDs and revision. Unknown categories map to the current sink.
Enforced: backend/schedules/api.py::restore_blocks, backend/schedules/planning.py::plan_commands, backend/schedules/persistence.py::persist_command_diff

#### Scenario: Changed restore
- **WHEN** a restore differs from the current blocks
- **THEN** all existing rows are replaced by the restored list and, in an Undo chain, each accepted restore advances the revision once

Tests: backend/tests/test_restore.py::TestRestoreBlocks::test_restore_replaces_all_blocks, backend/tests/test_undo_revisions.py::test_contiguous_undo_chain_uses_each_accepted_restore_revision

#### Scenario: One invalid entry
- **WHEN** a restore list contains a valid block and one with an empty title
- **THEN** the response is 400 and the existing blocks are unchanged

Tests: backend/tests/test_restore.py::TestRestoreBlocks::test_restore_atomicity

#### Scenario: Overlapping restore list
- **WHEN** two restored blocks overlap
- **THEN** the response is 400

Tests: backend/tests/test_restore.py::TestRestoreBlocks::test_restore_overlapping_blocks_rejected

#### Scenario: Deleted category in the snapshot
- **WHEN** a restored block names a category that no longer exists
- **THEN** it is stored in the sink category

Tests: backend/tests/test_restore.py::TestRestoreBlocks::test_restore_unknown_category_folds_to_sink

### Requirement: Signed restore provenance
The system SHALL sign each serialized block's `restore_proof` over schedule ID, block ID, title and origin. Restore MUST apply a valid proof's origin, use `unknown` when no proof is sent, and reject the whole request with 400 for an invalid or cross-schedule proof or a non-positive or duplicate proof `id`.
Enforced: backend/schedules/provenance.py::restore_proof, backend/schedules/provenance.py::origin_from_restore_proof, backend/schedules/api.py::restore_blocks

#### Scenario: Restore an imported block after deletion
- **WHEN** a deleted calendar-imported block is restored with its original ID and proof
- **THEN** it is recreated with origin `calendar`; with a changed title or ID the request is 400; without a proof it is recreated as `unknown`

Tests: backend/tests/test_ai_calendar_privacy.py::test_restore_proof_preserves_import_after_delete_and_rejects_tampering

#### Scenario: Proof from another day
- **WHEN** a block's proof from one date is sent to another date's restore
- **THEN** the response is 400 and the target day's blocks keep their origin

Tests: backend/tests/test_ai_calendar_privacy.py::test_restore_proof_cannot_cross_schedule

### Requirement: Schedule page bootstrap under the shared lock
The system SHALL read an existing schedule page in one read transaction without reserving the SQLite writer. Missing Schedule or policy rows MUST be created under `run_user_maintenance`; only the request that creates the Schedule may set `auto_draft_pending`. Exhausted SQLite contention MUST return 503 with `Retry-After: 1`.
Enforced: backend/schedules/views.py::schedule_view, backend/schedules/views.py::_read_schedule_page, backend/schedules/views.py::_create_schedule_page_rows

#### Scenario: Existing day while another connection writes
- **WHEN** another connection holds the SQLite writer and the day and its policies already exist
- **THEN** the page GET returns 200 with the current blocks and revision

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_existing_schedule_get_reads_during_independent_writer

#### Scenario: Two concurrent first visits
- **WHEN** two requests open the same absent day at once
- **THEN** one Schedule row is created and exactly one response has `auto_draft_pending: true`

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_two_first_visits_create_once_and_signal_once

#### Scenario: Existing day with missing policies
- **WHEN** a Schedule exists but settings, preferences or categories do not
- **THEN** those rows are created and `auto_draft_pending` is false

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_existing_day_with_missing_policies_bootstraps_without_autodraft

#### Scenario: First-use creation while the writer is held
- **WHEN** rows must be created but another connection holds the writer for every attempt
- **THEN** the response is 503 with `Retry-After: 1` and no row is created

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_schedule_get_creation_contention_returns_controlled_503, backend/tests/test_schedule_mutations_sqlite.py::test_missing_policy_under_writer_returns_controlled_503

### Requirement: Admin schedule surfaces are inspection only
The system SHALL deny add, change and delete permissions on the Django admin for Schedule and TimeBlock, so days change only through the revision-checked API.
Enforced: backend/schedules/admin.py::ScheduleInspectionOnly

#### Scenario: Admin opens a schedule
- **WHEN** a staff user opens the admin page for a schedule
- **THEN** the page renders without allowing writes

Tests: backend/tests/test_admin.py::TestScheduleAdmin::test_day_and_policy_admin_surfaces_are_inspection_only, backend/tests/test_admin.py::TestScheduleAdmin::test_inspection_page_renders_without_allowing_writes

### Requirement: Column-scoped diff persistence
The system SHALL persist an accepted diff by deleting, then updating, then creating blocks, saving only the columns whose values changed. An empty diff MUST perform no database write. Row-level `ValidationError` or `IntegrityError` is wrapped with the action index; `OperationalError` MUST propagate unwrapped.
Enforced: backend/schedules/persistence.py::persist_command_diff, backend/schedules/persistence.py::PersistenceError

#### Scenario: Metadata PATCH during a concurrent time change
- **WHEN** a PATCH changes only title and completion while the stored times change underneath
- **THEN** only `title` and `is_completed` are saved and the newer times survive

Tests: backend/tests/test_views.py::TestBlockDetail::test_non_time_patch_preserves_concurrent_time_update
