# Feature 0087: Configurable default gap between blocks (#258)

**Status, 23 October 2026:** implemented in PR #265. Full automated suites passed, and [production desktop/mobile verification](../BLOCK_GAP_PRODUCTION_VERIFICATION.md) on release `a2e6133` confirmed 0/10/20 across fresh sessions, real untimed AI placement, explicit-placement precedence, Undo and narrow-screen validation. Acceptance below combines automated contract coverage with those live scenarios; it does not claim every edge case was exercised in production.

Add `default_block_gap_minutes` to the existing per-user preferences contract and expose it under Settings → Schedule. Pass the normalized value through chat context capture, prompt construction, and automatic placement. Preserve the initial-window gap shrinking implemented in feature 0086 and explicit-placement behavior related to #185.

**Requirements retained verbatim**

- Add a per-user default gap setting, expressed in minutes, under Settings → Schedule.
- Keep 10 minutes as the default for users who have not customized it.
- Allow 0 minutes for back-to-back blocks and positive values for longer breaks. Define and validate the supported range and step consistently in the UI and API.
- Persist the preference across reloads and sessions, and use it wherever the current default gap is applied. The backend placement logic and AI instructions must use the same value.
- Treat it as a default: explicit non-overlapping start times and explicitly requested gaps take precedence. Changing the setting must not move existing blocks.
- Update help text and API documentation to describe the configurable value.

For example, with a 5-minute gap and an existing block ending at 10:00, an untimed add may start at 10:05 if its duration fits before the next occupied block and within the day window. With 0 minutes, it may start at 10:00.

**Technical contract**

| Property | Decision |
|---|---|
| Field | `default_block_gap_minutes`, consistent across model, DTO, JSON, and TypeScript |
| Storage | Non-null Django `PositiveSmallIntegerField` |
| Supported values | Integers from **0 through 120**, inclusive, in **5-minute steps** |
| Default | **10 minutes**, including existing preference rows and newly created rows |
| Validation | Reject booleans, strings, floats, null, arrays, objects, out-of-range integers, and integers not divisible by five |
| Read fallback | Normalize malformed persisted values to 10 without rewriting the row; preserve valid zero |
| Scope | Default spacing for untimed chat adds; explicit times and explicitly requested gaps take precedence |

Five-minute steps match the placement grid. The two-hour maximum permits longer breaks while bounding initial-window retries to 24 levels.

Implement the following tasks sequentially using **TDD red → green → refactor**. Before each production change, run its new behavioral tests and confirm the intended failure. Compatibility controls may already pass.

**1. Preferences, persistence, and API**

Files and functions to change or create:

| File | Changes |
|---|---|
| `backend/templates_mgr/preference_defaults.py` — **new** | Define ORM-independent default, minimum, maximum, and step constants, usable by models, prompts, and the pure planner. |
| [backend/templates_mgr/models.py:5](../../backend/templates_mgr/models.py) | Extend `UserPreferences`; add the field with default 10 and Django minimum/maximum validators plus a small custom step validator (Django has none built in). Model validators only fire on `full_clean()`; API enforcement is `is_valid_default_block_gap_minutes()`. Update its UI-only description. |
| `backend/templates_mgr/migrations/0006_userpreferences_default_block_gap_minutes.py` — **new** | Add the non-null field, depending on `0005_userpreferences_chat_suggestions`. Existing rows receive 10; preserve theme and suggestions. |
| [backend/templates_mgr/preferences.py:30](../../backend/templates_mgr/preferences.py) | Extend `UserPreferencesDTO`, `get_user_preferences()`, and `ui_preferences_payload()`. Add `is_valid_default_block_gap_minutes()` and `normalize_default_block_gap_minutes()` for strict validation and read fallback. |
| [backend/templates_mgr/api.py:501](../../backend/templates_mgr/api.py) | Extend `_prefs_to_dict()` and `user_preferences()`. Validate the entire PATCH before writing; perform preference writes through `run_user_maintenance()` under the shared User lock. Return controlled lock-conflict responses with `private, no-store`. |
| [backend/schedules/views.py:121](../../backend/schedules/views.py) | Extend `_read_schedule_page()`’s directly constructed DTO with the normalized stored gap. Preserve its existing read transaction and first-use bootstrap path. |
| [backend/templates_mgr/admin.py](../../backend/templates_mgr/admin.py) | Make `UserPreferencesAdmin` and `UserPreferencesInline` inspection-only through their permission methods, preventing administrative gap edits or preference deletion from bypassing the policy lock. |
| [backend/tests/test_user_preferences_api.py](../../backend/tests/test_user_preferences_api.py) | Extend helper, serializer, API, isolation, and Inertia-prop tests. Update complete-response expectations to include the new field. |
| `backend/tests/test_user_preferences_migration.py` — **new** | Verify upgrade from migration 0005 and restore migration leaf nodes afterward. |
| [backend/tests/test_admin.py](../../backend/tests/test_admin.py) | Cover inspection permissions for both preferences admin surfaces. |

**Red — write failing tests first**

- Missing preferences row resolves to 10; saved 0, 5, 20, and 120 survive subsequent reads.
- Migration backfills an existing row to 10 without changing owner, theme, or suggestions.
- PATCH → GET, Settings remount, and a newly authenticated `Client` session retain the saved value.
- Two users retain independent values; supplied ownership keys cannot redirect a write.
- Invalid values return the exact field error below and preserve every saved preference, including in mixed-field PATCHes. Invalid first-use requests create no preferences row.
- Malformed stored values resolve to 10 without write-on-read; valid zero never becomes 10.
- GET, PATCH, Settings, Schedule, and Analytics expose the same normalized field.
- Theme-only and suggestions-only PATCHes preserve the gap; same-value gap PATCH succeeds.
- Preference updates preserve existing block identities, fields, schedule status, and revision.
- Admin and inline writes cannot bypass the serialized settings path.

**Green — minimum implementation**

1. Generate the field migration with `make makemigrations`; inspect its dependency, default, and validators.
2. Add strict validation and normalization. Do not coerce input or use truthiness to resolve defaults.
3. Extend both serializers and both DTO construction paths.
4. Validate all recognized PATCH fields before entering the write callback. Write only supplied fields under `run_user_maintenance()` and serialize the resulting state inside that callback.
5. Preserve the existing authentication, body-size, partial-update, and unknown-key conventions.

API contract:

- `GET /api/user/preferences/` and successful PATCH return HTTP 200 with the complete preferences object: existing `theme` and `chat_suggestions`, plus integer `default_block_gap_minutes`.
- PATCH accepts the new field alone, for example `{"default_block_gap_minutes":5}`, or together with existing editable fields.
- Omission preserves the saved value. Zero is valid; null is invalid.
- Invalid gap response: HTTP 400, `{"errors":{"default_block_gap_minutes":"Must be an integer from 0 to 120 minutes in 5-minute increments."}}`.
- Keep errors as field-keyed strings, without echoing rejected values.
- Preserve `errors.body` for malformed/non-object JSON and bodies without recognized fields; preserve HTTP 413 for oversized bodies.
- Preserve `Cache-Control: private, no-store` on view-generated success and error responses. Lock exhaustion uses the existing HTTP 409 `schedule_changed` envelope with that header. `schedule_changed_response()` in `backend/schedules/mutations.py` does not set `Cache-Control` itself, so the preferences view must add the header to this 409 explicitly; cover it with a test.

**Refactor after green**

Keep normalization shared between DTO and ORM serializers. Keep constants independent of Django models so importing them does not introduce ORM access into the planner.

Verify with:

- `uv run pytest backend/tests/test_user_preferences_api.py backend/tests/test_user_preferences_migration.py backend/tests/test_admin.py -q`

**2. Chat context, prompt, and placement**

Files and functions to change:

| File | Changes |
|---|---|
| [backend/ai/views.py:421](../../backend/ai/views.py) | Extend `_ai_context_fingerprint()`, `_load_ai_context_sync()`, and `_apply_actions_sync()` with the normalized chat gap. |
| [backend/ai/service.py:375](../../backend/ai/service.py) | Have `run_chat()` pass the captured gap into the prompt builder without accessing the ORM asynchronously. |
| [backend/ai/prompts.py:49](../../backend/ai/prompts.py) | Extend `build_system_prompt_chat()` with a gap keyword defaulting to the shared 10. Interpolate the configured value and describe its retry behavior. |
| [backend/ai/mutation_planner.py:732](../../backend/ai/mutation_planner.py) | Add a `default_block_gap_minutes` keyword to `plan_mutations()`, defaulting to the shared 10; pass it to `_find_auto_slot()` instead of `AUTO_PLACEMENT_GAP_MINUTES`. |
| [backend/tests/test_ai_mutation_planner.py](../../backend/tests/test_ai_mutation_planner.py) | Extend `TestAutoPlacement` and `TestAutoPlacementGapPreference`; update `_plan()` to accept an explicit gap. Replace constant-monkeypatch tests with parameter-based coverage. |
| [backend/tests/test_ai_prompts_command_chat.py](../../backend/tests/test_ai_prompts_command_chat.py) | Parameterize prompt wording and explicit-placement precedence tests. |
| [backend/tests/test_ai_service_chat.py](../../backend/tests/test_ai_service_chat.py) | Inspect mocked provider messages to verify captured gap interpolation and fallback. |
| [backend/tests/test_ai_views_chat.py](../../backend/tests/test_ai_views_chat.py) | Extend auto-placement integration and changed-context coverage. |
| [backend/tests/test_ai_pending_intents.py](../../backend/tests/test_ai_pending_intents.py) | Cover gap changes invalidating saved intent context. |
| [backend/tests/test_ai_chat_requests.py](../../backend/tests/test_ai_chat_requests.py) | Cover completed-response replay after the preference changes. |
| [backend/tests/test_schedule_mutations_sqlite.py](../../backend/tests/test_schedule_mutations_sqlite.py) | Exercise preference PATCH against an independently held SQLite writer reservation using `copied_database` and `run_on_copy()`. |

**Red — write failing tests first**

- Saved 5 places a 25-minute add at 10:05–10:30 between occupied 09:30–10:00 and 10:35 onward; verify spacing on both sides.
- Saved 0 permits 10:00–10:25 between touching neighbors. Missing customization retains current 10-minute behavior.
- Custom 20 derives retries 15, 10, 5, 0; preserve the existing 10:15–10:40 reduced-gap scenario.
- A roomy scenario respects the maximum 120-minute preference; narrow and near-midnight windows remain safe.
- Zero has no retry levels. If its initial window is too short, retain its unpadded forward-search fallback.
- Preserve full-gap initial results, right-aligned retries, off-grid-neighbor rounding, fresh local-time floor, non-today window start, multiple-add occupancy, and day-window limits.
- A fully occupied day and an unusable initial window with only insufficiently padded later holes produce `no_slot`, a server-owned ask, and no writes.
- Explicit non-overlapping adds and moves remain exact even beside neighbors with less than the configured gap; no gap-restoring question appears.
- With default 20, explicitly requested 0- or 5-minute relative gaps are accepted when their concrete times are valid. A violated explicit request still triggers the existing relative-add guard.
- Capture the same saved value in provider instructions and persisted placement; cover 0, custom values, and the 10 fallback.
- Changing this user’s gap during a provider call returns `409 schedule_changed` for action, ask, and empty-action responses. Another user’s gap change does not invalidate the request.
- An unchanged saved gap between context capture and apply does not produce a spurious `409 schedule_changed`; capture and apply-time recompute use identical normalization.
- Changing the gap invalidates a pending intent. Completed same-ID receipt replay still returns the original response without another provider call or mutation.
- Under independent SQLite contention, PATCH returns the controlled conflict without changing preferences or blocks; succeeds after release.

**Green — context flow**

1. In `_load_ai_context_sync()`, resolve preferences under the existing User lock for chat. Capture the normalized integer on the schedule object alongside `_schedule_window` and `_categories`.
2. Include that integer in the chat policy fingerprint through a new optional chat-only fingerprint argument. `_load_ai_context_sync()` is shared with the draft path (`generate-draft`, `_apply_draft_sync()`): gate the capture and the fingerprint argument on chat mode so the draft capture and its apply-time recompute stay byte-identical and draft behavior and fingerprint are unchanged (the argument defaults to absent and is omitted from the fingerprint when absent). Add a red regression test: changing the user's gap does not invalidate a draft generation, and draft apply still succeeds.
3. In `run_chat()`, read the captured value, falling back to the shared default for standalone callers, and pass it explicitly to `build_system_prompt_chat()`.
4. In `_apply_actions_sync()`, reread normalized preferences under the mutation lock. Compare the fingerprint before planning, including for ask/no-op responses.
5. Pass the confirmed value explicitly to `plan_mutations()`. Continue calculating the placement floor from fresh apply-time local time.

Prompt wording must state the configured symmetric preference, decreasing five-minute retries only in the initial window, and full-gap later search. For zero, describe back-to-back placement without suggesting nonexistent retry levels. Explicit valid times and requested gaps take precedence; ordinary untimed adds still omit both times.

**Green — placement algorithm**

Preserve [ `_find_auto_slot()` ](../../backend/ai/mutation_planner.py) and [ `_padded_auto_intervals()` ](../../backend/ai/mutation_planner.py) behavior, supplying the saved gap:

1. Use the existing forward floor and duration: current local time rounded upward for today, day-window start otherwise; default duration remains 25 minutes.
2. Sort accepted raw candidate intervals. The initial window ends at the first block whose end is after the floor, using its start as the boundary; otherwise use day end. A block covering or starting at the floor makes this window empty.
3. Pad neighboring occupancy on both sides by configured gap `g`, clamping padding to day bounds in integer minutes. Call `find_slot()` forward on the five-minute grid and retain its result as the full-gap fallback.
4. Return that fallback immediately if the initial window is empty or the result ends within it.
5. Otherwise retry **only the initial window**, with gaps `g−5, g−10, …, 0`. For each trial, right-align the block before the next neighbor minus the trial gap, or before day end when no neighbor follows. Round the candidate end down to the grid.
6. Reject a trial whose start precedes the forward floor or whose interval overlaps trial-padded occupancy on either side.
7. Accept the first valid trial. If none fits, return the original full-gap fallback; later windows never receive reduced-gap searches.
8. With `g=0`, padding is absent and the retry sequence is empty. Half-open intervals may touch.
9. Large values use the same descending sequence and clamped arithmetic; they never wrap times or require spacing from the day boundary itself.
10. Preserve final interval/overlap validation, action ordering, outcomes, and `no_slot` handling. Each accepted automatic add contributes its raw interval to subsequent placement.

`find_slot()` itself already accepts arbitrary occupied intervals and needs no policy change. Explicit placements continue through their existing validation path without gap padding.

**Refactor after green**

Remove the obsolete hardcoded planner constant and fixed-gap comments. Keep padding and search pure. Retain the existing defensive non-grid helper regression as private-helper coverage; it must not imply that the preferences API accepts seven minutes.

Verify with:

- `uv run pytest backend/tests/test_ai_mutation_planner.py backend/tests/test_free_slot.py backend/tests/test_ai_prompts_command_chat.py backend/tests/test_ai_service_chat.py backend/tests/test_ai_views_chat.py backend/tests/test_ai_relative_add_guard.py backend/tests/test_ai_pending_intents.py backend/tests/test_ai_chat_requests.py backend/tests/test_schedule_mutations_sqlite.py -q`

**3. Settings control, help text, and documentation**

Files and functions to change or create:

| File | Changes |
|---|---|
| [frontend/src/types/index.ts:126](../../frontend/src/types/index.ts) | Extend `UiPreferences` with optional numeric `default_block_gap_minutes` for partial/stale props. |
| `frontend/src/utils/blockGap.ts` — **new** | Mirror backend constants; add `isValidDefaultBlockGap()` and `resolveDefaultBlockGap()` with strict numeric checks and zero-safe fallback. |
| [frontend/src/composables/usePreferences.ts:16](../../frontend/src/composables/usePreferences.ts) | Add and export `saveDefaultBlockGap()` using the existing preferences PATCH endpoint. |
| `frontend/src/components/settings/DefaultBlockGapEditor.vue` — **new** | Add labeled numeric input, validation, save/error/status handling, and synchronization with accepted preferences. Functions: `validate()`, `save()`, and `firstError()`. |
| [frontend/src/components/settings/SettingsSchedulePanel.vue](../../frontend/src/components/settings/SettingsSchedulePanel.vue) | Mount the editor below `DayWindowEditor` in the existing Schedule panel. |
| [frontend/src/components/settings/SettingsTemplatesRulesPanel.vue:60](../../frontend/src/components/settings/SettingsTemplatesRulesPanel.vue) | Replace fixed 10/5-minute help text with reactive configured-gap wording and a reference to Settings → Schedule. |
| `frontend/tests/DefaultBlockGapEditor.test.ts` — **new** | Exercise the real preferences wrapper with mocked HTTP and Inertia reloads. |
| [frontend/tests/Settings.test.ts](../../frontend/tests/Settings.test.ts) | Verify control placement under Schedule. |
| [frontend/tests/SettingsPanels.test.ts](../../frontend/tests/SettingsPanels.test.ts) | Replace fixed-gap assertions with configured, zero, and fallback cases. |
| [docs/api.md:187](../../docs/api.md) and [User Preferences:562](../../docs/api.md) | Document the field, complete responses, PATCH validation/errors, defaults, lock conflicts, and generalized placement algorithm. |
| [RULES.md:53](../../RULES.md) | Replace fixed-gap policy with configurable spacing, exact retry semantics, explicit precedence, and unchanged-existing-block guarantee. |
| [docs/ARCHITECTURE.md:37](../../docs/ARCHITECTURE.md) | Update the hardcoded-gap description and identify captured preferences as chat policy. |

**Red — write failing tests first**

- Render persisted 0/custom values and fallback 10; verify input minimum 0, maximum 120, and step 5.
- Reject blank, fractional, out-of-range, and non-step input before HTTP; preserve zero.
- Saving sends only `default_block_gap_minutes` to `/api/user/preferences/`.
- Disable duplicate submissions while saving and refreshing.
- On success, reload only `ui_preferences`; accepted props update the editor and Rules help text.
- Remounting with saved props retains the value.
- Show field errors first, then `detail`/`body` fallbacks. Failed saves do not claim success or alter accepted preferences.
- A failed refresh after successful PATCH reports that saving succeeded but refreshing failed.
- Verify the control belongs to Schedule and saving invokes no block mutation endpoint.

**Green — minimum implementation**

Use a number input labeled **“Default gap between blocks (minutes)”**, with Save, associated help/error text, and accessible status feedback. Validate the draft separately from the accepted value; blank input must not become zero.

Help text:

> Prefer this gap before and after blocks added through chat without a start time. Choose 0–120 minutes in 5-minute steps; 0 allows back-to-back blocks. The gap may shrink in 5-minute steps to fit the initial free window. Explicit times and requested gaps take precedence. Existing blocks are not moved.

Show the current normalized preference reactively. Explain that later windows retain the full configured gap. Use existing theme tokens and wrapping form styles.

After successful PATCH, refresh only `ui_preferences` through `router.reload()`. Keep save state through refresh completion, synchronize from accepted props, and handle callbacks after component disposal following the existing editor pattern.

**Refactor after green**

Share frontend bounds and fallback resolution between the editor and Rules help text. Remove fixed-gap assertions while retaining existing duration, grid, event-forwarding, and settings-navigation coverage.

Verify with:

- `cd frontend && npm test -- tests/DefaultBlockGapEditor.test.ts tests/Settings.test.ts tests/SettingsPanels.test.ts`

**Final verification**

After all focused suites pass:

- `uv run python backend/manage.py makemigrations --check --dry-run`
- `make check`
- `make frontend-build`

Confirm the migration test uses the test database, all provider calls are mocked, and preference changes preserve existing schedules. Run these commands during implementation; this read-only planning task does not execute migrations or tests.

**Acceptance criteria — verbatim**

- [x] Users can view and change their default gap in Settings.
- [x] The saved value is isolated per user and survives reloads and new sessions.
- [x] Users without a saved customization retain the current 10-minute behavior.
- [x] Auto-placement respects the configured gap on both sides of a new block, including 0 minutes, while preserving overlap checks and day-window constraints.
- [x] Explicit non-overlapping placements are honored without a question or shift solely to restore the default gap.
- [x] Changing the preference leaves existing blocks unchanged.
- [x] Invalid values produce clear validation errors without changing the saved preference.
- [x] Tests cover persistence, validation, per-user isolation, default fallback, zero/custom gaps, and no available slot.

**Note (rebased on main 560e03f):** PRs #263/#264 touched `prompts.py`, `service.py` (`run_chat` null `task_id` normalization), `pending_intents.py`, `relative_add_guard.py` and `docs/api.md`; they do not change the gap contract. Line anchors above are approximate; locate by function name. Keep #263/#264 behavior (null add target normalization, pending-sibling prompt wording) intact.
