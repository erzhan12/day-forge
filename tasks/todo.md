# TODO

<!-- Track current work items here as checkable items -->

## Phase 4 — AI Command Bar

- [x] Add `openai` dep + `LLM_*` settings
- [x] `backend/ai/schemas.py` — action validators
- [x] `backend/ai/prompts.py` — SYSTEM_PROMPT + user message builder
- [x] `backend/ai/service.py` — `run_command()` + error taxonomy
- [x] `backend/ai/views.py` — `ai_command` view
- [x] Register URL `api/ai/schedules/<date>/command/`
- [x] Backend tests (service + view)
- [x] `frontend/src/composables/useAI.ts`
- [x] `frontend/src/components/CommandBar.vue`
- [x] Wire CommandBar into `Schedule.vue`; extend `UndoAction["type"]`
- [x] Frontend tests (`useAI`, `CommandBar`)
- [x] Document endpoint in `docs/api.md` + env vars in `.claude/rules/project.md`
- [ ] Manual end-to-end test with a real `LLM_API_KEY` (English + Russian commands)

## Phase 5 — Templates, Rules & Drafts

### Backend

- [x] `templates_mgr.models`: add `user` FK to `Template` and `Rule`; unique `(user, type)` on `Template`
- [x] `templates_mgr` migration `0002_user_fk` — wipes orphan rows; document in docstring
- [x] `seed_templates --user <username>` required; no fallback
- [x] `templates_mgr/admin.py`: list_filter user, list_display user
- [x] `ai.models.AIInteraction.kind` choices=("command", "draft"), default "command"
- [x] AI migration `0004_aiinteraction_kind`
- [x] `LLM_DRAFT_MODEL`, `LLM_DRAFT_RATE_LIMIT_PER_HOUR`, `LLM_HISTORY_DAYS` settings
- [x] `ai/prompts.py`: `SYSTEM_PROMPT_DRAFT`, `build_draft_user_message`, `_format_block_line` dict refactor + adapters
- [x] `ai/schemas.py`: `validate_draft_response` (rejects non-`add`)
- [x] `ai/service.py`: `run_draft`, `AIDraftResult`
- [x] `ai/views.py`: `ai_generate_draft` view + `_rate_limit_drafts_per_user` decorator
- [x] `_log_interaction(kind=...)`; new code paths log `kind="draft"`
- [x] `Schedule.mark_active_if_draft()` + wire into `create_block`, `block_detail`, `reorder_blocks`, `ai_command` (only when `len(parsed_actions) > 0`)
- [x] `restore_blocks` does NOT flip status (verified by tests)
- [x] `templates_mgr.api`: REST CRUD for templates + rules, per-user scoped
- [x] `templates_mgr.views.settings_view` Inertia page
- [x] URLs: `/settings/`, `/api/templates/`, `/api/rules/`, `/api/ai/schedules/<date>/generate-draft/`
- [x] `schedule_view`: `auto_draft_pending` (one-shot) + `has_template_for_type` (ongoing) props

### Frontend

- [x] `frontend/src/types/index.ts`: `Template`, `TemplateBlock`, `Rule`, extend `Schedule.status`, add `"draft"` to `UndoAction["type"]`
- [x] `frontend/src/pages/Settings.vue`
- [x] `frontend/src/components/TemplateEditor.vue` (form-based, two slots; DnD deferred)
- [x] `frontend/src/components/RulesList.vue` (priority arrows, inline edit, toggle, delete)
- [x] `frontend/src/components/DraftBadge.vue`
- [x] `frontend/src/components/RegenerateDraftButton.vue` (disabled state when `!hasTemplate`)
- [x] `frontend/src/composables/useTemplates.ts`, `useRules.ts`, `useDraft.ts`
- [x] `useAI`/`useSchedule`/`useUndo` reload props → `["blocks", "schedule"]`
- [x] `useDrag.startDrag`: honor `isDisabled` callback
- [x] `GapSlot`: honor `disabled` prop
- [x] `Schedule.vue`: auto-draft watcher, undo for `"draft"` type, spinner overlay, inline error
- [x] `DateNavigator`: settings gear + slots for status/actions

### Tests + docs

- [x] Backend tests: prompts, schemas, service, views, status flow, templates API, schedule_view
- [x] Updated existing test_models / test_seed_command for user-FK
- [x] `docs/api.md`: templates + rules + draft endpoints
- [x] `RULES.md`: status-flip rules, ownership, partial-reload props
- [x] `docs/features/0005_MANUAL_TEST.md`
- [ ] Manual end-to-end test with a real `LLM_API_KEY`

### Deploy notes

- Run migrations after pulling: `uv run python backend/manage.py migrate` — `templates_mgr.0002_user_fk` wipes any existing global templates and rules. Re-seed per user with `seed_templates --user <name>`.

## Phase 6 — Analytics & End-of-Day Review

### Backend

- [x] `analytics.models.DailyReview`: add `planned_minutes_by_category`, `completed_minutes_by_category` JSON fields, `updated_at`, `completion_rate` property
- [x] `analytics/migrations/0002_review_aggregates.py`
- [x] `Schedule.mark_active_on_edit()` (replaces `mark_active_if_draft`) — DB-conditional UPDATE, handles draft AND reviewed source
- [x] `Schedule.mark_reviewed_if_active()`
- [x] Update all call sites in `schedules/api.py`, `ai/views.py`
- [x] `ANALYTICS_STREAK_THRESHOLD`, `ANALYTICS_STREAK_WINDOW_DAYS` settings (validated at import)
- [x] `analytics/services.py`: `compute_review_stats`, `recompute_review_from_schedule`, `compute_streak`
- [x] `analytics/views.py`: `analytics_view` (Inertia), `mark_reviewed`, `update_review_notes`
- [x] URLs: `/analytics/<date>/`, `/api/analytics/schedules/<date>/mark-reviewed/`, `/api/analytics/reviews/<pk>/notes/`
- [x] `analytics/admin.py`: extend list_display with completion %, notes excerpt, updated_at
- [x] `ai/prompts.py`: append `(completed: X/Y)` per history line when DailyReview exists

### Frontend

- [x] `frontend/src/types/index.ts`: `CategoryMinutes`, `DailyReview`, `StreakInfo`
- [x] `frontend/src/utils/categoryColors.ts` (extracted from TimeBlock.vue)
- [x] `frontend/src/composables/useAnalytics.ts` (markReviewed + saveNotes)
- [x] `frontend/src/components/{CompletionBar,CategoryBreakdown,StreakCounter,SkippedTasks}.vue`
- [x] `frontend/src/pages/Analytics.vue`
- [x] `frontend/src/pages/Schedule.vue`: "View analytics" link in actions slot
- [x] `frontend/src/components/TimeBlock.vue`: import categoryColors from shared util

### Tests + docs

- [x] `test_analytics_models.py`, `test_analytics_services.py`, `test_analytics_views.py`
- [x] `test_settings_validation.py` (env var validation)
- [x] Extend `test_status_flow.py` with `mark_active_on_edit` (incl. stale-instance recovery), `mark_reviewed_if_active`, reviewed-unfreezes-on-edit
- [x] Extend `test_ai_prompts_draft.py` with completion suffix case
- [x] Frontend tests: `useAnalytics`, `CompletionBar`, `CategoryBreakdown`, `StreakCounter`, `SkippedTasks`, `Analytics.vue`
- [x] `docs/api.md`: analytics endpoints
- [x] `RULES.md`: status matrix, conditional UPDATE rationale, body-after-lock rationale, streak/skipped semantics, frozen-vs-recompute
- [x] `docs/features/0006_MANUAL_TEST.md`
- [ ] Manual end-to-end test with a real `LLM_API_KEY`

## Follow-ups (discovered during manual testing)

### UX / Rules

- [ ] **Auto-bump default priority for new Rules.** Today every new rule
  lands at `priority=0` (hardcoded in `RulesList.vue:44`'s `createRule({...,
  priority: 0 })` call). Adding a second rule produces two rules at
  priority 0 → the user has to click ▲ once just to see ordering change,
  and the priority arrows look like a no-op on a single rule. Better:
  default to `max(existing.priority) + 1` so each new rule lands on top
  with a unique priority. Either compute on the frontend before POST, or
  push the default into the backend (`templates_mgr.api._parse_rule_create_payload`)
  so curl users get the same behaviour. Backend-side default is preferable
  — single source of truth and consistent across clients. Discovered while
  walking Test 3 of `docs/features/0005_MANUAL_TEST.md`.

- [ ] **Disabled-arrow tooltip on a single Rule.** Both ▲ and ▼ are
  disabled when there's only one rule (`:disabled="idx === 0"` and
  `:disabled="idx === localRules.length - 1"` both true). Currently
  silent — the user sees greyed-out arrows with no explanation. Add a
  `title` attribute like "Add another rule to reorder" so the affordance
  is self-documenting. Pairs naturally with the auto-bump task above.

- [ ] **Compact Rule priorities on add/delete.** Combined with the
  auto-bump task above, priorities will only grow monotonically over
  time. Concretely: start with `[r1=0, r2=1]`, delete `r1`, add `r3` →
  `[r2=1, r3=2]`. After many add/delete cycles the user sees badge values
  like "Priority 47" on the only rule, and eventually hits the API-layer
  upper bound (validated in `templates_mgr/api.py`). Compact to
  `0..N-1` after every list-mutation so:
  * default priority for the next new rule is always trivially `len(existing)`
  * badge values stay small and meaningful
  * no drift over the lifetime of an account

  Backend-side compaction in the `delete` and `create` views (single
  transaction with the actual mutation) is the natural place. Frontend
  picks it up via the existing partial reload of the rules list.

  Alternative: hide the numeric priority badge entirely — sort key is
  internal, users only care about ▲/▼ ordering. Either approach
  resolves the same root issue. Discovered while walking Test 3
  (delete with `[r1=0, r2=1]` leaves the survivor at priority 1, not 0).

### Playwright e2e tooling

- [ ] **Makefile target for the playwright scripts.** Right now each
  is invoked via `cd frontend && node scripts/playwright/<name>.mjs`.
  At ≥4 scripts the friction is real. Add a `make e2e` (or
  `e2e:layout` / `e2e:race` / `e2e:isolation`) so scripts are
  discoverable from `make help` and the invocation is one keystroke.
  Suggested by `claude-review` on PR #13.

- [ ] **`frontend/scripts/playwright/README.md`.** Up to PR #13 we
  have 4 e2e scripts; deferred earlier as "premature for 2". Add a
  short README documenting: prereqs (Django + Vite + ``playwright``
  test user creation snippet), how to run individual scripts and any
  shared assumptions (seed dates, idempotent setup, etc.). Pair with
  the Makefile follow-up above. Suggested by `claude-review` on PR
  #13 and PR #11.

- [ ] **Extract magic numbers in playwright scripts.** `await page.waitForTimeout(1500)`,
  the 30-iteration login wait loops, etc. Pull out as named
  `WAIT_FOR_PATCH_MS` / `LOGIN_POLL_MAX_TRIES` / etc. Trivial
  readability cleanup. Suggested by `claude-review` on PR #13.
