## MODIFIED Requirements

### Requirement: Pending intent continuation
The system SHALL let a request referencing an open intent by id and version apply only actions that answer saved missing fields within saved targets, each permission once. Expanded actions return 409 `pending_intent_scope` unless a guard question applies; a stale, expired or changed-context intent returns 409 `pending_intent_stale` before the provider call.
Enforced: backend/ai/pending_intents.py::capture, backend/ai/pending_intents.py::finish

#### Scenario: Answer resolves once
- **WHEN** the user answers the pending question within its scope
- **THEN** the change applies, the intent becomes resolved and a second answer returns 409

Tests: backend/tests/test_ai_pending_intents.py::test_answer_uses_server_scope_and_resolves_once, backend/tests/test_ai_pending_concurrency.py::test_two_processes_answer_one_intent

#### Scenario: Reply widens the scope
- **WHEN** the reply's actions go beyond the saved targets or fields
- **THEN** the response is 409 `pending_intent_scope`, nothing is written and the intent stays open

Tests: backend/tests/test_ai_pending_intents.py::test_expanded_actions_are_rejected_atomically, backend/tests/test_ai_pending_intents.py::test_repeated_question_cannot_expand_target_or_fields, backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_scope_rejects_expansion, backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_derived_duration_is_locked

#### Scenario: Stale or foreign intent
- **WHEN** the intent is closed, expired, of another owner or day, has an old version, or the schedule or policy context changed
- **THEN** the response is 409 `pending_intent_stale` without a provider call or rate-limit token, and an outdated intent is marked stale

Tests: backend/tests/test_ai_pending_intents.py::test_stale_or_foreign_scope_does_not_call_provider, backend/tests/test_ai_pending_intents.py::test_gap_change_invalidates_pending_intent, backend/tests/test_ai_pending_intents.py::test_deleted_schedule_is_not_recreated_by_an_old_intent, backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_scope_rejects_stale_reference

#### Scenario: Follow-up question
- **WHEN** a continuation ends with another question
- **THEN** the same intent's version increases, unanswered siblings are retained, and the expiry is not extended

Tests: backend/tests/test_ai_pending_intents.py::test_ask_only_turn_advances_version_without_extending_expiry, backend/tests/test_ai_pending_intents.py::test_remaining_sibling_is_retained_after_one_answer

#### Scenario: Relative-guard question during a continuation
- **WHEN** a continuation is blocked by the relative-add guard
- **THEN** no permission is consumed, the saved items stay unchanged even if the reply proposes pending work, and a corrected answer applies

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_reask_preserves_multiple_permissions

#### Scenario: Partial multi-add completion
- **WHEN** an answer applies some of several saved adds
- **THEN** the remaining adds stay pending with the accepted block IDs, and replaying an accepted add is rejected atomically

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_multi_add_can_complete_in_parts

## ADDED Requirements

### Requirement: Scope for relative-add guard questions
The system SHALL save one add permission per add the relative-add guard interrupts on a fresh turn: title, category and a derivable duration known, start and end missing. Model and replay-guard questions get none; a model copy of an interrupted add is replaced. Other actions are not saved.
Enforced: backend/ai/pending_intents.py::relative_guard_add_items, backend/ai/pending_intents.py::merge_guard_items, backend/ai/pending_intents.py::finish, backend/ai/views.py::_relative_guard_response

#### Scenario: Interrupted adds become permissions
- **WHEN** the guard asks about one or several executable adds
- **THEN** each becomes a pending permission in action order and an answer naming the anchor applies them

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_fresh_relative_guard_saves_scope_and_accepts_anchor_answer, backend/tests/test_ai_relative_guard_recovery.py::test_fresh_relative_guard_keeps_all_pending_adds

#### Scenario: Duration sources
- **WHEN** an interrupted add has an explicit duration or a positive five-minute interval
- **THEN** that duration is known; otherwise it is missing

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_scope_duration_sources

#### Scenario: Structured siblings
- **WHEN** the model also returns pending work
- **THEN** distinct siblings are kept, and a copy of an interrupted add is dropped unless its known duration differs

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_preserves_structured_pending_sibling, backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_scope_overflow_is_rejected

#### Scenario: Only adds are saved
- **WHEN** the interrupted turn also removes or updates a block
- **THEN** only the adds are saved, and a reply repeating the other action returns 409

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_mixed_turn_keeps_only_adds

#### Scenario: Other questions keep their scope
- **WHEN** the model asks without pending actions, or the replay guard asks
- **THEN** no executable scope is derived

Tests: backend/tests/test_ai_pending_intents.py::test_old_format_question_has_no_executable_scope, backend/tests/test_ai_relative_guard_recovery.py::test_replay_guard_does_not_seed_relative_scope

#### Scenario: New command during the question
- **WHEN** a bound reply is reinterpreted as a new relative add
- **THEN** the old intent is cancelled and the new one holds only the new command's adds

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_new_command_during_guard_question_gets_its_own_scope

### Requirement: Guard question before scope rejection
The system SHALL answer a continuation that fails the scope check with the relative-add guard's question when the guard has one and every reply action is an add matching the title and category of a distinct saved add whose start and end are missing. The scope, expiry and schedule stay unchanged; every other reply keeps the 409.
Enforced: backend/ai/pending_intents.py::finish, backend/ai/pending_intents.py::probe_allowed, backend/ai/views.py::_relative_guard_probe_sync

#### Scenario: Untimed answer after an anchor reply
- **WHEN** the user names the anchor and the model returns an untimed add
- **THEN** the response asks for a start time after that anchor, nothing is written and the version advances

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_untimed_answer_gets_time_question

#### Scenario: Guard has no question
- **WHEN** the guard is silent for the reply, the replay guard flags it, or the schedule context changed
- **THEN** the 409 stands, the intent stays open and nothing is applied

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_scope_failure_without_guard_question_stays_409, backend/tests/test_ai_relative_guard_recovery.py::test_probe_fallbacks_keep_scope_409_on_replay_hit, backend/tests/test_ai_relative_guard_recovery.py::test_probe_fallbacks_keep_scope_409_on_changed_context

#### Scenario: Reply outside the identity gate
- **WHEN** the scope is empty, the reply names an unsaved title, carries a non-add action, or the saved add already has a start
- **THEN** the guard is not consulted and the 409 stands

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_probe_is_not_consulted_for_unscoped_replies

#### Scenario: Untimed independent sibling
- **WHEN** a continuation times the related add but leaves an independent sibling untimed
- **THEN** the 409 stands until every pending add is timed

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_untimed_independent_sibling_stays_409
