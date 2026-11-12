# templates/rules Specification

## Purpose
Each user keeps a priority-ordered list of free-text AI rules that shape AI schedule suggestions. This spec covers the rules list API: create, patch and delete, the per-user rule cap, priority bounds and compaction, and atomic priority swaps. Rule access is scoped to the owning user.

## Requirements

### Requirement: List rules
The system SHALL return `GET /api/rules/` as `{"rules": [...]}` with only the authenticated user's rules, ordered by descending `priority` then ascending `id`, each serialized as `{id, text, is_active, priority}`.
Enforced: backend/templates_mgr/api.py::rules_collection

#### Scenario: Highest priority first
- **WHEN** a user has rules with different priorities
- **THEN** the rule with the highest priority is listed first

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_list_orders_by_priority, backend/tests/test_models.py::TestRule::test_ordering_by_priority

#### Scenario: Other users' rules are excluded
- **WHEN** another user also owns rules
- **THEN** the response lists only the requesting user's rules

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_list_per_user_only

### Requirement: Create rule
The system SHALL create a rule on `POST /api/rules/` and respond `201` with the serialized rule. `text` is required, trimmed and at most 500 characters; `is_active` defaults to `true`; a rule created without `priority` SHALL be placed at the top of the list.
Enforced: backend/templates_mgr/api.py::rules_collection, backend/templates_mgr/api.py::_parse_rule_create_payload

#### Scenario: Create a rule
- **WHEN** an authenticated user posts a rule with valid `text`
- **THEN** the response is `201` with `{id, text, is_active, priority}`

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_create_rule

#### Scenario: Rule without priority goes to the top
- **WHEN** a user with rule "Rule A" creates "Rule B" without a priority
- **THEN** the list order is "Rule B", "Rule A"

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_create_without_priority_defaults_to_top

#### Scenario: Invalid field types
- **WHEN** a rule is posted with blank `text`, a non-boolean `is_active`, or a non-integer or boolean `priority`
- **THEN** the response is `400` with the error keyed by that field

### Requirement: Rule count cap
The system SHALL refuse to create a rule through the API when the user already has 100 rules, responding `400` with `errors.rules`.
Enforced: backend/templates_mgr/api.py::rules_collection

#### Scenario: Hundred-and-first rule
- **WHEN** a user who has 100 rules posts a new rule
- **THEN** the response is `400` with `errors.rules = "You have reached the maximum of 100 rules."` and no rule is created

### Requirement: Rule priority bounds
The system SHALL reject an explicit rule `priority` outside `-1000000..1000000` with `400` and `errors.priority` on both create and PATCH, before any compaction.
Enforced: backend/templates_mgr/api.py::_parse_rule_create_payload, backend/templates_mgr/api.py::_parse_rule_patch_payload

#### Scenario: Priority out of range on create
- **WHEN** a rule is posted with `priority: 1000001` or `priority: -1000001`
- **THEN** the response is `400` with `errors.priority`

Tests: backend/tests/test_templates_api.py::TestRulePriorityBounds::test_create_rejects_priority_above_max, backend/tests/test_templates_api.py::TestRulePriorityBounds::test_create_rejects_priority_below_min

#### Scenario: Priority at maximum
- **WHEN** a rule is posted with `priority: 1000000`
- **THEN** it is accepted and placed at the top of the list

Tests: backend/tests/test_templates_api.py::TestRulePriorityBounds::test_create_accepts_priority_at_max_and_places_rule_on_top

#### Scenario: Priority bounds on PATCH
- **WHEN** a rule is patched with an out-of-range priority, or with exactly `-1000000`
- **THEN** the out-of-range value returns `400` and the minimum is accepted

Tests: backend/tests/test_templates_api.py::TestRulePriorityBounds::test_patch_rejects_out_of_range_priority, backend/tests/test_templates_api.py::TestRulePriorityBounds::test_patch_accepts_priority_at_min

### Requirement: Rule priorities are compacted on API create and delete
The system SHALL renumber the acting user's rules to contiguous priorities `0..N-1` after every `POST /api/rules/` and `DELETE /api/rules/{pk}/`, keeping the `-priority, id` order so the top rule holds `N-1`. An explicit create priority SHALL be compacted too.
Enforced: backend/templates_mgr/api.py::_compact_rule_priorities

#### Scenario: Create after sparse priorities
- **WHEN** a user with rules at priorities 5 and 9 creates a rule without a priority
- **THEN** the new rule returns priority 2 and the list priorities are `[2, 1, 0]`

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_create_compacts_priorities

#### Scenario: Equal priorities keep id order
- **WHEN** compaction runs over rules that share a priority
- **THEN** the lower id stays ahead in the resulting order

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_compaction_preserves_id_tiebreak_for_equal_priorities

#### Scenario: Other users are untouched
- **WHEN** one user creates a rule
- **THEN** another user's rule priorities are not renumbered

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_compaction_does_not_touch_other_users_rules

#### Scenario: Delete compacts survivors
- **WHEN** a rule is deleted
- **THEN** the remaining rules have contiguous priorities `0..N-1` in the same order, and repeated add/delete cycles keep values small

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_delete_compacts_priorities, backend/tests/test_templates_api.py::TestRulesCRUD::test_delete_last_rule_compacts_to_empty, backend/tests/test_templates_api.py::TestRulesCRUD::test_add_delete_cycle_keeps_priorities_small

### Requirement: Patch rule
The system SHALL partially update `text`, `is_active` and `priority` on `PATCH /api/rules/{pk}/`, ignore unknown keys, respond `200` with the serialized rule, and SHALL NOT compact priorities. A body with no editable field SHALL return `400` with `errors.body`.
Enforced: backend/templates_mgr/api.py::rule_detail, backend/templates_mgr/api.py::_parse_rule_patch_payload

#### Scenario: Patch text
- **WHEN** the owner patches a rule's `text`
- **THEN** the response is `200` with the updated rule

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_patch_rule

#### Scenario: Patch leaves gaps in place
- **WHEN** a user with rules at priorities 0 and 5 patches the second rule's text
- **THEN** the priorities stay 0 and 5

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_patch_does_not_compact_priorities

#### Scenario: Empty patch
- **WHEN** a PATCH body contains none of `text`, `is_active` or `priority`
- **THEN** the response is `400` with `errors.body = "No editable fields supplied."`

### Requirement: Delete rule
The system SHALL delete the authenticated user's rule on `DELETE /api/rules/{pk}/`, compact the remaining priorities, and respond `{"ok": true}`.
Enforced: backend/templates_mgr/api.py::rule_detail

#### Scenario: Owner deletes rule
- **WHEN** the owner deletes one of their rules
- **THEN** the response is `200 {"ok": true}` and the rule no longer exists

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_delete

### Requirement: Cross-user rule access returns 404
The system MUST respond `404 {"errors": {"detail": "Not found."}}` for PATCH or DELETE on a rule id that does not exist, belongs to another user, or was deleted before the user lock was acquired.
Enforced: backend/templates_mgr/api.py::rule_detail

#### Scenario: Patch another user's rule
- **WHEN** a user patches a rule id owned by another user
- **THEN** the response is `404`

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_cross_user_patch_returns_404

#### Scenario: Rule deleted while waiting for the lock
- **WHEN** the target rule is deleted before the locked re-fetch
- **THEN** the PATCH returns `404` without writing

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_rule_patch_404_when_target_deleted_under_lock

### Requirement: Swap rule priorities
The system SHALL atomically exchange the `priority` values of two of the user's rules on `POST /api/rules/swap/` with body `{"a": id, "b": id}`, responding `200 {"rules": [...]}` with only the two swapped rows. If the write fails, neither rule SHALL change.
Enforced: backend/templates_mgr/api.py::rules_swap, backend/schedules/http.py::swap_ordering_field, backend/schedules/http.py::parse_swap_body

#### Scenario: Swap two owned rules
- **WHEN** a user swaps two of their rules
- **THEN** the response is `200` and each rule now holds the other's former priority

Tests: backend/tests/test_templates_api.py::TestRuleSwap::test_swap_two_rules_swaps_priority

#### Scenario: Invalid ids
- **WHEN** the ids are equal, non-integer, or booleans
- **THEN** the response is `400` with `errors.body`

Tests: backend/tests/test_templates_api.py::TestRuleSwap::test_swap_equal_ids_returns_400, backend/tests/test_templates_api.py::TestRuleSwap::test_swap_non_int_id_returns_400, backend/tests/test_templates_api.py::TestRuleSwap::test_swap_bool_id_returns_400

#### Scenario: Malformed or oversized body
- **WHEN** the body is not a JSON object, is invalid JSON, or exceeds 100 KB
- **THEN** the response is `400` for the first two cases and `413` for the oversized body

Tests: backend/tests/test_templates_api.py::TestRuleSwap::test_non_dict_body_returns_400, backend/tests/test_templates_api.py::TestRuleSwap::test_swap_invalid_json_returns_400, backend/tests/test_templates_api.py::TestRuleSwap::test_swap_oversized_body_returns_413

#### Scenario: Missing or cross-user id
- **WHEN** one of the ids does not exist or belongs to another user
- **THEN** the response is `404` and no priority changes

Tests: backend/tests/test_templates_api.py::TestRuleSwap::test_swap_missing_id_returns_404, backend/tests/test_templates_api.py::TestRuleSwap::test_swap_cross_user_id_returns_404

#### Scenario: Write failure mid-swap
- **WHEN** the bulk update raises during the swap
- **THEN** both rules keep their original priorities

Tests: backend/tests/test_templates_api.py::TestRuleSwap::test_swap_rolls_back_on_bulk_update_failure

#### Scenario: Anonymous swap
- **WHEN** an unauthenticated client posts to `/api/rules/swap/`
- **THEN** the request is redirected to login

Tests: backend/tests/test_templates_api.py::TestRuleSwap::test_unauthenticated_redirects
