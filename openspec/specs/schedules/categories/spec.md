# schedules/categories Specification

## Purpose
Each user owns a small catalog of time-block categories: an immutable slug plus an editable label, palette colour and order, with exactly one sink row and one new-block default. This capability covers the catalog bootstrap, the create, update, delete and swap endpoints under `/api/user/categories/`, the remap of references to the sink on delete, and the shared per-user mutation rate limit built on the generic fixed-window helper and its `schedules.W002` startup warning.

## Requirements

### Requirement: Catalog bootstrap on first read
The system SHALL seed the four default categories for a user whose catalog is empty on first read, and SHALL return the existing rows unchanged when the catalog already has rows.
Enforced: backend/schedules/categories.py::ordered_categories, backend/schedules/category_palette.py::SEED_CATEGORIES

#### Scenario: First read seeds the default catalog
- **WHEN** the catalog of a user with no category rows is read
- **THEN** exactly four rows are created in this order: `work` "Work" `blue` (new-block default), `personal` "Personal" `violet`, `health` "Health" `emerald`, `other` "Other" `gray` (sink), with sort orders 0 to 3

Tests: backend/tests/test_categories.py::TestSeedOnFirstRead::test_first_read_seeds_exact_four_rows

#### Scenario: Repeated reads are idempotent
- **WHEN** the catalog is read twice
- **THEN** both reads return the same rows and the user still has exactly four categories

Tests: backend/tests/test_categories.py::TestSeedOnFirstRead::test_repeated_reads_are_idempotent

#### Scenario: Non-empty catalog is not repaired
- **WHEN** the user already has at least one category row
- **THEN** the read returns the existing rows and seeds nothing

Tests: backend/tests/test_categories.py::TestSeedOnFirstRead::test_no_repair_when_catalog_non_empty

#### Scenario: Catalogs are per user
- **WHEN** two users read their catalogs
- **THEN** each user gets their own four rows with disjoint IDs

Tests: backend/tests/test_categories.py::TestSeedOnFirstRead::test_catalogs_are_isolated_between_users

#### Scenario: Transient seed contention is retried
- **WHEN** the first seeding attempt raises an IntegrityError or OperationalError
- **THEN** seeding is retried (up to three attempts) and the four seeded rows are returned instead of an error

Tests: backend/tests/test_categories.py::TestSeedOnFirstRead::test_seed_recovers_from_integrityerror, backend/tests/test_categories.py::TestSeedOnFirstRead::test_seed_recovers_from_operationalerror

### Requirement: Catalog listing endpoint
The system SHALL answer `GET /api/user/categories/` with `{"categories": [...]}` for the authenticated user, ordered by sort order then ID, bootstrapping the catalog if empty. Each row SHALL carry `id`, `slug`, `label`, `color_id`, `sort_order`, `is_sink` and `is_new_block_default`.
Enforced: backend/schedules/category_api.py::categories_collection, backend/schedules/categories.py::serialize_category

#### Scenario: Listing returns the seeded catalog
- **WHEN** an authenticated user with no categories sends `GET /api/user/categories/`
- **THEN** the response is 200 with the four seeded rows in catalog order, each with the seven serialized fields

### Requirement: Catalog storage constraints
The system MUST keep per-user slugs unique, keep labels unique per user after trim and case folding, allow at most one sink row and one new-block-default row per user, and allow `is_sink` only on the `other` slug. Slugs are at most 32 characters and labels at most 64.
Enforced: backend/schedules/models.py::Category.Meta.constraints, backend/schedules/models.py::Category

#### Scenario: Oversized label fails model validation
- **WHEN** a category with a 65-character label is validated
- **THEN** validation fails

Tests: backend/tests/test_categories.py::TestModelValidation::test_oversized_label_fails_full_clean

#### Scenario: Long custom slug is accepted
- **WHEN** a category with an 18-character custom slug is validated
- **THEN** validation passes, because slugs are not restricted to a fixed choice list

Tests: backend/tests/test_categories.py::TestModelValidation::test_long_slug_passes_full_clean

### Requirement: Sink and default lookup
The system SHALL resolve the sink row and the new-block-default row from a loaded catalog, and MUST raise a RuntimeError instead of guessing when the catalog lacks either row.
Enforced: backend/schedules/categories.py::sink_category, backend/schedules/categories.py::default_category

#### Scenario: Missing sink raises
- **WHEN** the sink is looked up in a catalog with no sink row
- **THEN** a RuntimeError is raised

Tests: backend/tests/test_categories.py::TestCatalogInvariantGuards::test_sink_category_raises_on_missing_sink

#### Scenario: Missing default raises
- **WHEN** the new-block default is looked up in a catalog with no default row
- **THEN** a RuntimeError is raised

Tests: backend/tests/test_categories.py::TestCatalogInvariantGuards::test_default_category_raises_on_missing_default

### Requirement: Slug validation against the catalog
The system SHALL accept a category value only when it is a string matching a slug in the user's catalog. Non-strings MUST be rejected. Unknown strings MUST be rejected unless the caller asks for lenient mode, in which case they map to the sink slug.
Enforced: backend/schedules/categories.py::validate_slug

#### Scenario: Known slug passes through
- **WHEN** `health` is validated against the seeded catalog
- **THEN** `health` is returned

Tests: backend/tests/test_categories.py::TestValidateSlug::test_known_slug_passthrough

#### Scenario: Non-string rejected
- **WHEN** a list is validated as a category
- **THEN** a ValueError is raised

Tests: backend/tests/test_categories.py::TestValidateSlug::test_non_string_rejected

#### Scenario: Unknown slug rejected by default
- **WHEN** an unknown slug is validated in strict mode
- **THEN** a ValueError is raised

Tests: backend/tests/test_categories.py::TestValidateSlug::test_unknown_rejected_by_default

#### Scenario: Unknown slug folds to the sink in lenient mode
- **WHEN** an unknown slug is validated with `unknown_to_sink=True`
- **THEN** the sink slug `other` is returned

Tests: backend/tests/test_categories.py::TestValidateSlug::test_unknown_folds_to_sink_when_lenient

### Requirement: Create category
The system SHALL create a category on `POST /api/user/categories/` with `label` and `color_id`, returning 201 and the row. The label is trimmed and must be 1 to 64 characters; `color_id` must be a palette ID. The row is appended last and is neither sink nor default. Errors return 400 `{"errors": {"category": ...}}`.
Enforced: backend/schedules/category_api.py::categories_collection, backend/schedules/categories.py::create_category

#### Scenario: Label is trimmed and slugified
- **WHEN** a user creates `"  Deep  Work  "` with colour `amber`
- **THEN** the response is 201 with label `Deep  Work`, slug `deep-work`, colour `amber`, `is_sink` false and `is_new_block_default` false

Tests: backend/tests/test_categories.py::TestCreate::test_create_trims_and_slugifies

#### Scenario: Blank label rejected
- **WHEN** the label is only whitespace
- **THEN** the response is 400

Tests: backend/tests/test_categories.py::TestCreate::test_empty_label_rejected

#### Scenario: Label longer than 64 characters rejected
- **WHEN** the trimmed label is 65 characters long
- **THEN** the response is 400 with `errors.category` "Label must be between 1 and 64 characters."

#### Scenario: Colour outside the palette rejected
- **WHEN** `color_id` is `chartreuse`
- **THEN** the response is 400 with `errors.category` "Invalid color_id."

Tests: backend/tests/test_categories.py::TestCreate::test_invalid_color_rejected

#### Scenario: Non-string colour rejected cleanly
- **WHEN** `color_id` is a JSON array
- **THEN** the response is 400, not a server error

Tests: backend/tests/test_categories.py::TestCreate::test_non_string_color_returns_400_not_500

#### Scenario: Colours may be shared
- **WHEN** two categories are created with the same palette colour
- **THEN** both are created with 201

Tests: backend/tests/test_categories.py::TestCreate::test_shared_color_is_allowed

### Requirement: Category palette
The system SHALL accept exactly these colour IDs for categories: `blue`, `violet`, `emerald`, `gray`, `amber`, `rose`, `cyan`, `indigo`.
Enforced: backend/schedules/category_palette.py::PALETTE, backend/schedules/categories.py::create_category, backend/schedules/categories.py::update_category

#### Scenario: Palette IDs are the only accepted colours
- **WHEN** a create or update supplies a colour ID that is not one of the eight palette IDs
- **THEN** the request is rejected with 400 "Invalid color_id."

Tests: backend/tests/test_categories.py::TestCreate::test_invalid_color_rejected, backend/tests/test_categories.py::TestUpdate::test_non_string_color_patch_returns_400_not_500

### Requirement: Label uniqueness and catalog cap on create
The system MUST reject a new label that matches an existing label after trim and case folding, and MUST reject a create when the user already has eight categories.
Enforced: backend/schedules/categories.py::create_category, backend/schedules/categories.py::MAX_CATEGORIES

#### Scenario: Case-insensitive duplicate rejected
- **WHEN** `Focus` exists and the user creates `"  focus "`
- **THEN** the response is 400 and `errors.category` says the label already exists

Tests: backend/tests/test_categories.py::TestCreate::test_duplicate_label_case_insensitive_rejected

#### Scenario: Ninth category rejected
- **WHEN** the user has the four seeded rows plus four created rows and creates another
- **THEN** the response is 400 and `errors.category` mentions the maximum

Tests: backend/tests/test_categories.py::TestCreate::test_cap_of_eight_enforced

#### Scenario: Concurrent insert collision returns a clean error
- **WHEN** every insert attempt raises an IntegrityError on the unique constraints
- **THEN** after three attempts the create fails with 400 "A category with that label already exists."

Tests: backend/tests/test_categories.py::TestConcurrencyHardening::test_create_category_maps_integrityerror_to_clean_error, backend/tests/test_categories.py::TestConcurrencyHardening::test_create_category_integrityerror_returns_400_over_http

### Requirement: Slug derivation on create
The system SHALL derive the slug from the label by ASCII-folding, lowercasing and joining alphanumeric runs with `-`, capped at 32 characters, falling back to `category` when nothing remains, and SHALL add `-2`, `-3` and so on when the slug is taken.
Enforced: backend/schedules/categories.py::_slugify

#### Scenario: Colliding slug gets a numeric suffix
- **WHEN** `Deep Work` exists and the user creates `Deep-Work`
- **THEN** the new row is created with slug `deep-work-2`

Tests: backend/tests/test_categories.py::TestCreate::test_slug_collision_gets_suffix

#### Scenario: Label without ASCII letters or digits
- **WHEN** the label contains no characters that fold to ASCII letters or digits
- **THEN** the slug is `category` (or `category-2` and so on if taken)

### Requirement: Update category
The system SHALL update `label` and `color_id` on `PATCH /api/user/categories/{id}/` with the create rules, returning 200 and the row. `slug` and `is_sink` MUST be immutable, so a rename leaves block, template and rule references unchanged. The sink's label and colour stay editable.
Enforced: backend/schedules/category_api.py::category_detail, backend/schedules/categories.py::update_category

#### Scenario: Rename keeps the slug
- **WHEN** the user renames `work` to `Deep Work`
- **THEN** the response is 200 with label `Deep Work` and slug `work`

Tests: backend/tests/test_categories.py::TestUpdate::test_rename_keeps_slug

#### Scenario: Slug edit rejected
- **WHEN** the PATCH body contains `slug`
- **THEN** the response is 400 and `errors.category` says the field is immutable

Tests: backend/tests/test_categories.py::TestUpdate::test_slug_edit_rejected

#### Scenario: Sink flag edit rejected
- **WHEN** the PATCH body sets `is_sink` on the sink row
- **THEN** the response is 400

Tests: backend/tests/test_categories.py::TestUpdate::test_clear_is_sink_rejected

#### Scenario: Sink label and colour are editable
- **WHEN** the user patches the sink with label `Misc` and colour `indigo`
- **THEN** the response is 200 with the new label and colour and `is_sink` still true

Tests: backend/tests/test_categories.py::TestUpdate::test_sink_label_and_color_remain_editable

#### Scenario: Non-string colour rejected
- **WHEN** `color_id` is a JSON object
- **THEN** the response is 400, not a server error

Tests: backend/tests/test_categories.py::TestUpdate::test_non_string_color_patch_returns_400_not_500

#### Scenario: Duplicate label rejected
- **WHEN** the user renames a category to another row's label in a different letter case
- **THEN** the response is 400 "A category with that label already exists."

#### Scenario: Concurrent duplicate-label race returns 400
- **WHEN** the update raises an IntegrityError from the label constraint
- **THEN** the response is 400 "A category with that label already exists."

Tests: backend/tests/test_categories.py::TestConcurrencyHardening::test_patch_label_race_integrityerror_returns_400

### Requirement: New-block default promotion
The system SHALL accept only `is_new_block_default: true` on PATCH, making that row the only default. A request to clear the default MUST be rejected with 400; the default moves only by promoting another row.
Enforced: backend/schedules/categories.py::update_category

#### Scenario: Promotion leaves exactly one default
- **WHEN** the user patches `personal` with `is_new_block_default: true`
- **THEN** the response is 200 and `personal` is the only default in the catalog

Tests: backend/tests/test_categories.py::TestUpdate::test_default_promotion_leaves_exactly_one_default

#### Scenario: Clearing the default rejected
- **WHEN** the user patches the current default with `is_new_block_default: false`
- **THEN** the response is 400

Tests: backend/tests/test_categories.py::TestUpdate::test_unset_only_default_rejected

### Requirement: Delete category with remap to the sink
The system SHALL delete a non-sink category on `DELETE /api/user/categories/{id}/` with `{"ok": true}`, first moving its slug to the sink in the user's blocks, templates and travel rules, and adding its minutes in review maps to the sink's. Deleting the sink MUST be refused with 400.
Enforced: backend/schedules/category_api.py::category_detail, backend/schedules/categories.py::delete_category

#### Scenario: Sink cannot be deleted
- **WHEN** the user deletes the sink category
- **THEN** the response is 400, `errors.category` mentions the sink, and the row remains

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_sink_cannot_be_deleted

#### Scenario: Every reference form is remapped
- **WHEN** `focus` is used by a block, a template block, a travel rule and the planned and completed minute maps of a review, and `focus` is deleted
- **THEN** the block, the template entry and the rule use `other`, other template entries and an empty rule category are unchanged, `focus` minutes are added to `other` in both maps, and the row is gone

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_remaps_every_storage_form

#### Scenario: Malformed sink minutes are treated as zero
- **WHEN** a review map holds a non-numeric value for the sink and the deleted category has 30 minutes
- **THEN** the sink entry becomes 30

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_folds_into_malformed_sink_value

#### Scenario: Deleting the default promotes the sink
- **WHEN** the deleted category is the new-block default
- **THEN** the sink becomes the only default

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_of_default_promotes_sink

#### Scenario: Other users are untouched
- **WHEN** two users each have a `focus` category and one user deletes theirs
- **THEN** the other user's category, blocks, schedule revision and review are unchanged

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_isolated_from_other_user

### Requirement: Delete advances revisions and preserves frozen reviews
The system SHALL advance once the revision of each schedule whose blocks were remapped. A reviewed schedule's review tag SHALL advance only if it matched the revision before the remap; counts, notes and timestamps MUST stay unchanged, and a stale review stays stale.
Enforced: backend/schedules/categories.py::delete_category

#### Scenario: Current frozen review stays current
- **WHEN** a reviewed day at revision 4 with a review tagged 4 has a block in the deleted category
- **THEN** the day moves to revision 5, the tag moves to 5, counts, notes and `updated_at` are unchanged, and the minute maps move to the sink

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_keeps_current_review_frozen_across_consumers

#### Scenario: Stale review and unaffected days
- **WHEN** one affected day has a stale review and another day has no blocks in the deleted category
- **THEN** the affected day's revision advances while its stale tag stays put, and the unaffected day's revision and review tag do not change

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_does_not_revalidate_stale_review_or_bump_unaffected_day

### Requirement: Delete is atomic
The system MUST apply the block remap, review tag updates, template, rule and review-map remaps, default promotion and row deletion in one transaction; a failure part-way MUST leave all of them unchanged.
Enforced: backend/schedules/categories.py::delete_category, backend/schedules/categories.py::_category_write

#### Scenario: Injected failure rolls everything back
- **WHEN** the travel-rule remap fails during a delete
- **THEN** the block keeps its category, the category row remains, and the schedule revision and review tag are unchanged

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_rolls_back_on_injected_failure

#### Scenario: Repeated delete is a no-op
- **WHEN** an already-deleted category is deleted again
- **THEN** the service raises DoesNotExist and no schedule revision changes

Tests: backend/tests/test_categories.py::TestDeleteRemap::test_delete_does_not_revalidate_stale_review_or_bump_unaffected_day

### Requirement: Swap category order
The system SHALL exchange the sort orders of two of the user's categories on `POST /api/user/categories/swap/` with body `{"a": id, "b": id}`, returning 200 and `{"categories": [both rows]}`. IDs must be distinct plain integers (400 `errors.body` otherwise); a missing or foreign ID returns 404.
Enforced: backend/schedules/category_api.py::categories_swap, backend/schedules/categories.py::swap_categories, backend/schedules/http.py::parse_swap_body

#### Scenario: Sort orders are exchanged
- **WHEN** the user swaps `work` (0) and `personal` (1)
- **THEN** the response is 200 with `work` at 1 and `personal` at 0

Tests: backend/tests/test_categories.py::TestSwapAndOwnership::test_swap_exchanges_sort_order

#### Scenario: Foreign ID returns 404
- **WHEN** one of the IDs belongs to another user
- **THEN** the response is 404

Tests: backend/tests/test_categories.py::TestSwapAndOwnership::test_swap_cross_user_id_rejected

#### Scenario: Same or non-integer IDs rejected
- **WHEN** `a` equals `b`, or either is not a plain integer
- **THEN** the response is 400 with `errors.body` "a and b must be distinct integer category ids."

### Requirement: Ownership on detail endpoints
The system SHALL return 404 `{"errors": {"detail": "Not found."}}` from PATCH and DELETE for an ID that does not exist or belongs to another user, including a row removed concurrently between the lookup and the write, and MUST NOT change the foreign row.
Enforced: backend/schedules/category_api.py::category_detail

#### Scenario: Foreign PATCH returns 404
- **WHEN** a user patches another user's category
- **THEN** the response is 404 and the foreign label is unchanged

Tests: backend/tests/test_categories.py::TestSwapAndOwnership::test_patch_cross_user_returns_404

#### Scenario: Foreign DELETE returns 404
- **WHEN** a user deletes another user's category
- **THEN** the response is 404 and the foreign row remains

Tests: backend/tests/test_categories.py::TestSwapAndOwnership::test_delete_cross_user_returns_404

#### Scenario: Concurrent removal returns 404
- **WHEN** the row disappears after the endpoint lookup but before the update or delete
- **THEN** the response is 404, not a server error

Tests: backend/tests/test_categories.py::TestConcurrencyHardening::test_delete_racing_concurrent_delete_returns_404, backend/tests/test_categories.py::TestConcurrencyHardening::test_patch_racing_concurrent_delete_returns_404

### Requirement: Invalid JSON on category writes
The system SHALL reject a category create or swap body that is not valid JSON with 400 `{"errors": {"body": "Invalid JSON."}}` and no writes.
Enforced: backend/schedules/category_api.py::categories_collection, backend/schedules/category_api.py::categories_swap

#### Scenario: Undecodable body
- **WHEN** a create or swap request sends bytes that are not valid UTF-8 JSON
- **THEN** the response is 400 `{"errors": {"body": "Invalid JSON."}}`

Tests: backend/tests/test_http_json.py::test_invalid_encoding_uses_existing_endpoint_envelope

### Requirement: Shared category mutation rate limit
The system SHALL count create, PATCH, DELETE and swap against one per-user hourly counter `category_mutation_rl:<user_id>`, limited by `CATEGORY_MUTATION_RATE_LIMIT_PER_HOUR` (default 60). GET MUST NOT be counted. The check runs before body parsing and row lookup.
Enforced: backend/schedules/category_api.py::_rate_limited, backend/schedules/ratelimit.py::category_mutation_rate_limit_key, backend/day_forge/settings.py::CATEGORY_MUTATION_RATE_LIMIT_PER_HOUR

#### Scenario: Create blocked after the budget
- **WHEN** the budget is 2 and the user sends a third create within the hour
- **THEN** the response is 429 `{"errors": {"detail": "Rate limit exceeded. Try again later."}}` with `Retry-After: 3600`

Tests: backend/tests/test_categories.py::TestCategoryMutationRateLimit::test_create_blocked_after_budget_spent

#### Scenario: Reads are free
- **WHEN** the user sends five GETs and then three creates with a budget of 2
- **THEN** the GETs succeed, the first two creates succeed and the third is 429

Tests: backend/tests/test_categories.py::TestCategoryMutationRateLimit::test_get_reads_never_counted

#### Scenario: All write verbs share one counter
- **WHEN** a swap and a create spend a budget of 2 and the user then deletes an unknown ID
- **THEN** the delete returns 429 rather than 404, because the limit is checked before the lookup

Tests: backend/tests/test_categories.py::TestCategoryMutationRateLimit::test_all_verbs_share_one_counter

#### Scenario: PATCH and swap are gated
- **WHEN** the budget is already spent
- **THEN** a PATCH or a swap returns 429

Tests: backend/tests/test_categories.py::TestCategoryMutationRateLimit::test_patch_gated_after_budget, backend/tests/test_categories.py::TestCategoryMutationRateLimit::test_swap_gated_after_budget

#### Scenario: Budget is per user
- **WHEN** one user has spent their budget
- **THEN** another user can still create a category

Tests: backend/tests/test_categories.py::TestCategoryMutationRateLimit::test_budget_is_per_user

#### Scenario: Counter key shape
- **WHEN** the counter key is built for user 42
- **THEN** it is `category_mutation_rl:42`

Tests: backend/tests/test_ratelimit.py::test_category_mutation_rate_limit_key_shape

#### Scenario: Non-positive budget fails at startup
- **WHEN** `CATEGORY_MUTATION_RATE_LIMIT_PER_HOUR` is set to 0 or less
- **THEN** settings import raises ValueError

### Requirement: Fixed-window rate limit helper
The system SHALL consume one token per call from a cache counter whose first call anchors a 3600-second TTL; later calls use the cache's synchronous `incr` and keep that original TTL. A call SHALL be allowed while the count is at most the limit; rejected calls still count.
Enforced: backend/schedules/ratelimit.py::consume_rate_limit, backend/schedules/ratelimit.py::RATE_LIMIT_WINDOW_SECONDS

#### Scenario: Allows within budget, then blocks
- **WHEN** a key with limit 2 is consumed three times
- **THEN** the first two calls return true, the third returns false, and the counter reads 3

Tests: backend/tests/test_ratelimit.py::test_consume_rate_limit_allows_within_budget_then_blocks

#### Scenario: Window TTL is preserved
- **WHEN** a counter is incremented after its first call
- **THEN** the key keeps the TTL set by the first call

Tests: backend/tests/test_ratelimit.py::test_consume_rate_limit_preserves_window_ttl

### Requirement: Rate limit recovery after eviction
The system SHALL re-seed a counter that disappears between the seed attempt and the increment, giving the new window a full TTL and logging a warning once. If no counter can be established after the bounded retries, the call MUST fail closed.
Enforced: backend/schedules/ratelimit.py::consume_rate_limit, backend/schedules/ratelimit.py::_MAX_RESEED_ATTEMPTS

#### Scenario: Evicted key is re-seeded
- **WHEN** the key expires between the seed attempt and the increment
- **THEN** the call re-seeds it with a full 3600-second TTL and is allowed

Tests: backend/tests/test_ratelimit.py::test_consume_rate_limit_reseeds_via_add_after_genuine_eviction, backend/tests/test_ratelimit.py::test_consume_rate_limit_recovers_from_expiry_between_add_and_incr, backend/tests/test_ratelimit.py::test_consume_rate_limit_reseeded_window_has_full_ttl

#### Scenario: Recovering callers share the new window
- **WHEN** several callers concurrently find that the window expired between their seed attempt and increment
- **THEN** exactly one re-seeds the key and the others increment that new counter

Tests: backend/tests/test_ratelimit.py::test_consume_rate_limit_contention_single_add_winner_others_increment

#### Scenario: Failed increment on a live key keeps counting
- **WHEN** an increment fails once while the key still exists
- **THEN** the retry increments the existing counter instead of resetting it, so the limit still applies

Tests: backend/tests/test_ratelimit.py::test_consume_rate_limit_race_recovery_callers_share_one_window

#### Scenario: Repeated eviction fails closed
- **WHEN** the counter can neither be re-seeded nor incremented on any retry
- **THEN** the call returns false after one initial attempt plus three retries, logging one eviction warning

Tests: backend/tests/test_ratelimit.py::test_consume_rate_limit_repeated_eviction_fails_closed

### Requirement: Rate limit response envelope
The system SHALL report an exhausted budget as 429 `{"errors": {"detail": "Rate limit exceeded. Try again later."}}` with `Retry-After: 3600`. Connect counters use the key `connect_rl:<provider>:<user_id>`.
Enforced: backend/schedules/ratelimit.py::rate_limited_response, backend/schedules/ratelimit.py::connect_rate_limit_key

#### Scenario: Envelope and Retry-After
- **WHEN** the rate-limited response is built
- **THEN** it has status 429, header `Retry-After: 3600` and the fixed detail message

Tests: backend/tests/test_ratelimit.py::test_rate_limited_response_envelope_and_retry_after

#### Scenario: Connect key shape
- **WHEN** the connect key is built for provider `caldav` and user 42
- **THEN** it is `connect_rl:caldav:42`

Tests: backend/tests/test_ratelimit.py::test_connect_rate_limit_key_shape

### Requirement: Ineffective rate-limit cache warning
The system SHALL emit warning `schedules.W002` when `DEBUG` is false and the default cache backend is LocMemCache, FileBasedCache or DummyCache. The message names each backend's failure mode and the hint names RedisCache and PyMemcacheCache. The check does not block startup.
Enforced: backend/schedules/checks.py::warn_ineffective_cache_for_connect_rate_limits

#### Scenario: Ineffective backend in production
- **WHEN** `DEBUG` is false and the default cache is LocMemCache, FileBasedCache or DummyCache
- **THEN** exactly one `schedules.W002` warning is returned

Tests: backend/tests/test_checks.py::TestConnectRateLimitCacheWarning::test_w002_fires_on_each_ineffective_backend

#### Scenario: Shared backend
- **WHEN** `DEBUG` is false and the default cache is Redis or Memcached
- **THEN** no warning is returned

Tests: backend/tests/test_checks.py::TestConnectRateLimitCacheWarning::test_w002_silent_on_shared_backend

#### Scenario: Debug mode
- **WHEN** `DEBUG` is true, even with LocMemCache
- **THEN** no warning is returned

Tests: backend/tests/test_checks.py::TestConnectRateLimitCacheWarning::test_w002_silent_when_debug_true
