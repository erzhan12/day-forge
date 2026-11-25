## MODIFIED Requirements

### Requirement: Template block validation
The system SHALL accept `blocks` only as a list of at most `MAX_TEMPLATE_BLOCKS` (50) objects, each with a non-empty `title` of at most 255 characters, `%H:%M` start and end times on a 5-minute grid inside the user's schedule window (inclusive), start before end, and a `category` slug from the user's catalog. Failures SHALL return `400` with `errors.blocks` as a list of messages.
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
- **WHEN** a template is created or updated with 51 blocks
- **THEN** the response is `400` with `templates may not contain more than 50 blocks` and the stored template is unchanged

Tests: backend/tests/test_templates_api.py::TestTemplateBlockCap::test_create_one_over_cap_returns_400, backend/tests/test_templates_api.py::TestTemplateBlockCap::test_update_one_over_cap_returns_400_and_keeps_template

#### Scenario: Exactly the block limit
- **WHEN** a template is created or updated with 50 valid blocks
- **THEN** it is saved

Tests: backend/tests/test_templates_api.py::TestTemplateBlockCap::test_create_at_cap_succeeds, backend/tests/test_templates_api.py::TestTemplateBlockCap::test_update_at_cap_succeeds
