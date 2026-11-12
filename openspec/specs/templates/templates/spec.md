# templates/templates Specification

## Purpose
The `templates_mgr` app stores one weekday and one weekend schedule template per user, each a list of timed blocks. This spec covers how dates map to a template slot, the template CRUD API and the validation applied to template blocks. It also covers the cross-cutting rules for the app: the per-user write lock on policy mutations, the inspection-only admin and the `seed_templates` management command.

## Requirements

### Requirement: Weekday and weekend slot mapping
The system SHALL map a calendar date to the `weekend` template slot when `date.weekday()` is 5 or 6 (Saturday or Sunday), and to the `weekday` slot otherwise.
Enforced: backend/templates_mgr/models.py::Template.slot_type_for_date

#### Scenario: Saturday and Sunday map to weekend
- **WHEN** `Template.slot_type_for_date` is called with a Saturday or Sunday
- **THEN** it returns `weekend`

Tests: backend/tests/test_models.py::test_template_slot_type_for_date_covers_all_seven_weekdays

#### Scenario: Monday through Friday map to weekday
- **WHEN** `Template.slot_type_for_date` is called with a date from Monday to Friday
- **THEN** it returns `weekday`

Tests: backend/tests/test_models.py::test_template_slot_type_for_date_covers_all_seven_weekdays

### Requirement: One template per user per slot type
The system MUST allow at most one template per `(user, type)` pair, enforced by the `unique_user_template_type` database constraint. Different users may each own a template of the same type.
Enforced: backend/templates_mgr/models.py::Template.Meta.constraints

#### Scenario: Second template of the same type for one user
- **WHEN** a user who already owns a `weekday` template inserts another `weekday` template
- **THEN** the database rejects the row with an integrity error

Tests: backend/tests/test_models.py::TestTemplate::test_unique_user_type

#### Scenario: Two users each own a weekday template
- **WHEN** two different users each create a `weekday` template
- **THEN** both templates are stored

Tests: backend/tests/test_models.py::TestTemplate::test_same_type_different_users, backend/tests/test_templates_api.py::TestTemplatesCreate::test_two_users_can_each_have_weekday

### Requirement: List templates
The system SHALL return `GET /api/templates/` as `{"templates": [...]}` with only the authenticated user's templates, ordered by `type` and serialized as `{id, name, type, blocks}`. Unauthenticated requests SHALL be redirected to login.
Enforced: backend/templates_mgr/api.py::templates_collection

#### Scenario: Other users' templates are excluded
- **WHEN** an authenticated user requests `GET /api/templates/` and another user also owns templates
- **THEN** the response lists only the requesting user's templates

Tests: backend/tests/test_templates_api.py::TestTemplatesList::test_list_per_user_only

#### Scenario: Anonymous request
- **WHEN** an unauthenticated client requests `GET /api/templates/`
- **THEN** the response is a `302` redirect to login

Tests: backend/tests/test_templates_api.py::TestTemplatesList::test_requires_auth

### Requirement: Create template
The system SHALL create a template for the authenticated user on a valid `POST /api/templates/` and respond `201` with the serialized template. The stored name SHALL be whitespace-trimmed.
Enforced: backend/templates_mgr/api.py::templates_collection

#### Scenario: Valid template is created
- **WHEN** an authenticated user posts a non-empty `name`, a `type` of `weekday` or `weekend`, and valid `blocks`
- **THEN** the response is `201` with `{id, name, type, blocks}` and the template is owned by that user

Tests: backend/tests/test_templates_api.py::TestTemplatesCreate::test_creates_for_user

### Requirement: Duplicate template slot conflict
The system SHALL respond `409` with `errors.type` naming the slot, instead of a server error, when a template create or update would violate the `(user, type)` uniqueness constraint.
Enforced: backend/templates_mgr/api.py::templates_collection, backend/templates_mgr/api.py::template_detail

#### Scenario: Create a second weekday template
- **WHEN** a user who already owns a `weekday` template posts another `weekday` template
- **THEN** the response is `409` with `errors.type` stating that a template for this weekday slot already exists

Tests: backend/tests/test_templates_api.py::TestTemplatesCreate::test_unique_user_type_returns_409

#### Scenario: Update moves a template into an occupied slot
- **WHEN** a user PUTs `type: weekend` on their weekday template while they already own a weekend template
- **THEN** the response is `409` with `errors.type`

### Requirement: Template payload validation
The system SHALL reject a template create or update with `400` when the body is not a JSON object or is undecodable (`errors.body`), when `name` is blank or longer than 100 characters (`errors.name`), or when `type` is not `weekday` or `weekend` (`errors.type`). Bodies over 100 KB SHALL return `413`.
Enforced: backend/templates_mgr/api.py::_parse_template_payload, backend/common/http.py::parse_json_object

#### Scenario: Blank name
- **WHEN** a template is posted with `name` set to whitespace only
- **THEN** the response is `400` with `errors.name = "Name is required."`

#### Scenario: Unknown type
- **WHEN** a template is posted with `type: "holiday"`
- **THEN** the response is `400` with `errors.type = "Type must be 'weekday' or 'weekend'."`

#### Scenario: Undecodable body
- **WHEN** `POST /api/templates/` receives bytes that are not valid UTF-8 JSON
- **THEN** the response is `400` with `{"errors": {"body": "Invalid JSON."}}`

Tests: backend/tests/test_http_json.py::test_invalid_encoding_uses_existing_endpoint_envelope

### Requirement: Template block validation
The system SHALL accept `blocks` only as a list of at most 50 objects, each with a non-empty `title` of at most 255 characters, `%H:%M` start and end times on a 5-minute grid inside the user's schedule window (inclusive), start before end, and a `category` slug from the user's catalog. Failures SHALL return `400` with `errors.blocks` as a list of messages.
Enforced: backend/templates_mgr/api.py::validate_template_blocks

#### Scenario: Empty block title via the API
- **WHEN** a template is posted with a block whose `title` is empty
- **THEN** the response is `400`

Tests: backend/tests/test_templates_api.py::TestTemplatesCreate::test_invalid_block_returns_400

#### Scenario: Empty block title message
- **WHEN** `validate_template_blocks` receives a block with an empty `title`
- **THEN** the errors contain `block[0]: title is required`

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_missing_title_rejected

#### Scenario: Title too long
- **WHEN** a template block title exceeds 255 characters
- **THEN** validation reports `title too long`

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_title_too_long_rejected

#### Scenario: Unknown or non-string category
- **WHEN** a template block names a slug the user does not own, or a non-string category
- **THEN** validation fails with an `invalid category` message

Tests: backend/tests/test_templates_api.py::TestTemplatesCreate::test_invalid_category, backend/tests/test_categories.py::TestValidateTemplateBlocks::test_unknown_category_rejected, backend/tests/test_categories.py::TestValidateTemplateBlocks::test_non_string_category_rejected

#### Scenario: Off-grid time
- **WHEN** a template block starts at `09:07`
- **THEN** validation reports that times must align to 5-minute granularity

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_off_grid_time_rejected

#### Scenario: Time outside the user's window
- **WHEN** a template block falls outside the user's schedule window
- **THEN** validation fails with an error naming the window bounds

Tests: backend/tests/test_templates_api.py::TestTemplatesCreate::test_out_of_window, backend/tests/test_categories.py::TestValidateTemplateBlocks::test_outside_window_rejected

#### Scenario: Start not before end
- **WHEN** a template block has `start_time` equal to or after `end_time`
- **THEN** validation reports that `start_time` must be before `end_time`

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_start_after_end_rejected

#### Scenario: Too many blocks
- **WHEN** a template is saved with 51 blocks
- **THEN** validation reports that templates may not contain more than 50 blocks

### Requirement: Template blocks must not overlap
The system SHALL reject a template whose blocks overlap, treating each block as a half-open interval so a block may end exactly when the next starts. The overlap check SHALL run only when every block passed its individual checks.
Enforced: backend/templates_mgr/api.py::validate_template_blocks

#### Scenario: Overlapping blocks
- **WHEN** a template contains blocks `09:00-10:00` and `09:30-10:30`
- **THEN** validation fails with `blocks may not overlap`

Tests: backend/tests/test_templates_api.py::TestTemplatesCreate::test_overlap_rejected, backend/tests/test_categories.py::TestValidateTemplateBlocks::test_overlap_rejected

#### Scenario: Adjacent blocks
- **WHEN** a template contains blocks `09:00-10:00` and `10:00-11:00`
- **THEN** validation passes

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_adjacent_half_open_ok

### Requirement: Template validation uses the user's own schedule window
The system SHALL validate template block times against the requesting user's current schedule window, read under the user lock, so one user's window never affects another user's validation.
Enforced: backend/templates_mgr/api.py::templates_collection, backend/templates_mgr/api.py::template_detail

#### Scenario: Block outside a narrowed window
- **WHEN** the user's window is narrowed and a template block falls outside it
- **THEN** the response is `400` with an error naming the user's window bounds

Tests: backend/tests/test_templates_api.py::TestTemplatesCustomWindow::test_rejects_block_outside_narrowed_window

#### Scenario: Block inside a narrowed window
- **WHEN** the user's window is narrowed and every template block falls inside it
- **THEN** the template is accepted

Tests: backend/tests/test_templates_api.py::TestTemplatesCustomWindow::test_block_inside_narrowed_window_accepted

#### Scenario: Another user's narrow window
- **WHEN** a different user has a narrowed window
- **THEN** the requesting user's template is validated against their own window

Tests: backend/tests/test_templates_api.py::TestTemplatesCustomWindow::test_window_isolation_between_users

### Requirement: Narrowing the window does not rewrite stored templates
The system SHALL leave stored template blocks unchanged when the user's schedule window is narrowed, and SHALL reject a later save of those blocks if they now fall outside the window.
Enforced: backend/templates_mgr/api.py::template_detail

#### Scenario: Window narrowed after save
- **WHEN** a template with a block ending at `22:00` exists and the window end is changed to `21:00`
- **THEN** the stored template blocks are unchanged

Tests: backend/tests/test_templates_api.py::TestTemplatesCustomWindow::test_narrowing_window_does_not_mutate_stored_template

#### Scenario: Re-saving stale blocks
- **WHEN** the user PUTs the same out-of-window blocks after the window becomes `08:00-21:00`
- **THEN** the response is `400` with an error naming `08:00-21:00`

Tests: backend/tests/test_templates_api.py::TestTemplatesCustomWindow::test_editing_template_after_narrowing_rejects_stale_blocks

### Requirement: Missing block category defaults to the sink category
The system SHALL treat a template block without a `category` key as the user's sink category during validation, and the API SHALL store the sink slug explicitly on that block.
Enforced: backend/templates_mgr/api.py::validate_template_blocks, backend/templates_mgr/api.py::_parse_template_payload

#### Scenario: Validation of a block without category
- **WHEN** `validate_template_blocks` receives a block that has no `category` key
- **THEN** it returns no errors

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_missing_category_defaults_to_sink_and_passes

#### Scenario: Stored block without category
- **WHEN** a template is created or replaced through the API with a block that has no `category` key
- **THEN** the stored block carries the user's sink category slug

### Requirement: Template validation requires the category catalog
The system SHALL require callers of `validate_template_blocks` to pass the user's categories as a keyword-only argument, and SHALL reject explicit slugs that are not in that list.
Enforced: backend/templates_mgr/api.py::validate_template_blocks

#### Scenario: Categories omitted or positional
- **WHEN** `validate_template_blocks` is called without the `categories` keyword
- **THEN** it raises `TypeError`

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_categories_positional_raises, backend/tests/test_categories.py::TestValidateTemplateBlocks::test_categories_omitted_raises

#### Scenario: Explicit slug with an empty catalog
- **WHEN** a block names `work` and the categories list is empty
- **THEN** validation returns `["block[0]: invalid category 'work'"]`

Tests: backend/tests/test_categories.py::TestValidateTemplateBlocks::test_empty_categories_explicit_slug_rejected

### Requirement: Update template
The system SHALL treat `PUT /api/templates/{pk}/` as a full replacement of `name`, `type` and `blocks` (`blocks` defaults to `[]` when omitted), apply the same validation as create, and respond `200` with the serialized template.
Enforced: backend/templates_mgr/api.py::template_detail

#### Scenario: Valid replacement
- **WHEN** the owner PUTs a valid body to their template
- **THEN** the response is `200` with the updated `{id, name, type, blocks}`

Tests: backend/tests/test_templates_api.py::TestTemplateDetail::test_put_updates

### Requirement: Delete template
The system SHALL delete the authenticated user's template on `DELETE /api/templates/{pk}/` and respond `{"ok": true}`.
Enforced: backend/templates_mgr/api.py::template_detail

#### Scenario: Owner deletes template
- **WHEN** the owner sends `DELETE /api/templates/{pk}/`
- **THEN** the response is `200 {"ok": true}` and the template no longer exists

Tests: backend/tests/test_templates_api.py::TestTemplateDetail::test_delete

### Requirement: Cross-user template access returns 404
The system MUST respond `404 {"errors": {"detail": "Not found."}}` to PUT or DELETE on a template id that does not exist or belongs to another user, so ids cannot be enumerated.
Enforced: backend/templates_mgr/api.py::template_detail

#### Scenario: PUT another user's template
- **WHEN** a user PUTs to a template id owned by another user
- **THEN** the response is `404` and the other user's template keeps its name

Tests: backend/tests/test_templates_api.py::TestTemplateDetail::test_cross_user_returns_404

### Requirement: API policy writes run under the user write lock
The system SHALL run every template, rule and preference mutation made through the API, and the seed command, inside `run_user_maintenance`, which holds the per-user write lock for the whole write transaction. A busy SQLite lock SHALL be retried as a whole transaction, three attempts in total, then answered with `409` and `code: "schedule_changed"`.
Enforced: backend/templates_mgr/api.py::_policy_conflicts, backend/schedules/mutations.py::run_user_maintenance

#### Scenario: Rule writes take the lock first
- **WHEN** a rule is created, patched, deleted or swapped
- **THEN** the user lock is acquired before the rule count, re-fetch, or save

Tests: backend/tests/test_templates_api.py::TestRulesCRUD::test_rule_post_locks_user_before_count_and_create, backend/tests/test_templates_api.py::TestRulesCRUD::test_rule_patch_locks_user_before_refetch_and_save, backend/tests/test_templates_api.py::TestRulesCRUD::test_rule_delete_locks_user_before_refetch, backend/tests/test_templates_api.py::TestRuleSwap::test_user_lock_is_acquired

#### Scenario: Transient lock contention
- **WHEN** the first save of a new rule or template raises `database is locked` and the retry succeeds
- **THEN** the response is `201` and exactly one row exists

Tests: backend/tests/test_policy_mutation_lock.py::test_policy_busy_write_retries_whole_transaction

#### Scenario: Lock contention never clears
- **WHEN** all three attempts raise `database is locked`
- **THEN** the response is `409` with `code: "schedule_changed"` and no row is created

Tests: backend/tests/test_policy_mutation_lock.py::test_policy_busy_write_retries_whole_transaction

### Requirement: Admin is inspection only
The system SHALL register `Template`, `Rule` and `UserPreferences` in the Django admin, plus a `UserPreferences` inline on the User admin, as view-only surfaces that always deny add, change and delete.
Enforced: backend/templates_mgr/admin.py::PolicyInspectionMixin

#### Scenario: Preferences admin and inline
- **WHEN** an admin user opens the preferences admin or the User admin inline
- **THEN** view permission is granted and add, change and delete are denied

Tests: backend/tests/test_admin.py::test_preferences_admin_and_inline_inspection_only, backend/tests/test_admin.py::test_user_admin_preferences_inline_renders_and_rejects_policy_writes

#### Scenario: Template and rule admin
- **WHEN** an admin user opens the Template or Rule admin
- **THEN** view permission is granted and add, change and delete are denied

### Requirement: Seed templates command
The system SHALL provide `manage.py seed_templates --user <username>`, which creates the default weekday and weekend templates and two starter rules for that user only, under the user write lock. Existing items (template by type, rule by exact text) SHALL be skipped.
Enforced: backend/templates_mgr/management/commands/seed_templates.py::Command.handle

#### Scenario: First run
- **WHEN** `seed_templates --user <username>` runs for a user with no templates or rules
- **THEN** the user gets a weekday template with 6 blocks, a weekend template, and 2 rules

Tests: backend/tests/test_seed_command.py::TestSeedTemplates::test_creates_templates_and_rules, backend/tests/test_seed_command.py::TestSeedTemplates::test_weekday_template_blocks

#### Scenario: Second run
- **WHEN** `seed_templates` runs twice for the same user
- **THEN** the user still has two templates and two rules

Tests: backend/tests/test_seed_command.py::TestSeedTemplates::test_idempotent

#### Scenario: Missing or unknown user
- **WHEN** `seed_templates` runs without `--user` or with a username that does not exist
- **THEN** it raises `CommandError`

Tests: backend/tests/test_seed_command.py::TestSeedTemplates::test_requires_user_arg, backend/tests/test_seed_command.py::TestSeedTemplates::test_unknown_user

#### Scenario: Seeding two users
- **WHEN** the command runs for two different users
- **THEN** each user gets their own two templates

Tests: backend/tests/test_seed_command.py::TestSeedTemplates::test_per_user_isolation
