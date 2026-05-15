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
- [x] Manual end-to-end test with a real `LLM_API_KEY` (English + Russian commands)
  - Phase-4 single-shot `/command/` endpoint is no longer wired to the UI after the
    feature-0007 chat rewrite; the equivalent behavior is covered by the chat surface.
    Validated end-to-end with real LLM on 2026-05-15 via
    `ai-chat-single-turn-apply.mjs` (EN: "add 30-minute focus block at 10:00" →
    block created, status flipped to active) and `ai-chat-clarifying-question.mjs`
    (RU: "запланируй встречу" → assistant `ask` in Russian → "в 14:00 на час, рабочая"
    → block created).

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
- [x] Manual end-to-end test with a real `LLM_API_KEY`
  - Validated 2026-05-15 via `regenerate-422-fallback.mjs` against real LLM
    (Regenerate-button enable/disable contracts across template/no-template states all
    hold). Prompt-content invariants (per-day completion suffix) were validated
    separately on 2026-05-14 via `draft-prompt-history-suffix.mjs` with
    `LLM_DRAFT_CAPTURE_PROMPT_PATH` opt-in capture.

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
- [x] Manual end-to-end test with a real `LLM_API_KEY`
  - Validated 2026-05-15 via `analytics-unfreeze-on-edit.mjs` (steps A-F: unfreeze on
    drag / inline-edit / delete / restore + status-flow invariants all hold; Step G
    targeted the Phase-4 `/command/` endpoint via `waitForResponse(...'/command/')`,
    but `CommandBar.vue` now submits to `/chat/` after feature 0007 (PR #15) so the
    response matcher never fired and the script timed out — superseded by
    `ai-chat-single-turn-apply.mjs` which exercises the same `mark_active_on_edit`
    invariant against the current chat surface) and `skipped-tasks-today-aware.mjs`
    (today-aware skipped-task filter holds across past/today/future analytics pages).

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

- [ ] **Cleanup test data in `finally` for playwright scripts.** Currently
  scripts seed via `update_or_create` (idempotent across re-runs) and
  leave the data in place. `claude-review` on PR #14 suggested deleting
  the seeded schedules in the `finally` block to prevent state pollution.
  Counter-argument: leaving the data in place lets a developer inspect
  the DB after a failed run, which is genuinely useful. Resolution:
  add cleanup but gate behind `--cleanup` flag, default off. Suggested
  by `claude-review` on PR #14.

- [ ] **Pre-flight server-reachable check at the top of every playwright
  script.** Currently a script with Django/Vite down fails late with a
  cryptic ECONNREFUSED. A `fetch(BASE/accounts/login/, { method: 'HEAD' })`
  + clear "start them with `make run` / `make frontend-dev`" message at
  the top would shave debugging time for new contributors. Pairs with
  the test-utils.mjs follow-up below — same one-shared-helper file.
  Suggested by `claude-review` on PR #14.

- [ ] **`frontend/scripts/playwright/test-utils.mjs` shared helpers.**
  `login()`, `fail()`, the seed `execSync` boilerplate, the server
  pre-flight check are duplicated across 5+ scripts. Factor into one
  helpers module so each script is just its scenario logic. Touches
  every existing playwright script — defer to its own PR. Suggested
  by `claude-review` on PR #13 and PR #14, plus my own
  `/review-fix-loop-staged` review of PR #14.

- [ ] **Extract Django shell seeds to standalone scripts.** Each
  playwright script currently embeds its seed via a multi-line
  `execSync(... uv run python backend/manage.py shell -c "...")`
  template literal. Pull these out into `backend/scripts/seed-*.py`
  files (create the directory if needed) so seeds are auditable,
  testable, and editable with proper Python tooling. Suggested by
  `claude-review` on PR #14. Pairs naturally with the test-utils.mjs
  follow-up — the test-utils module would expose a single `seed()`
  helper that shells out to the new scripts.

- [ ] **Manual QA gate for feature 0007 chat dock before any production
  use.** PR #15 ships PR A of the multi-turn chat panel; the smoke
  checklist in the PR description is unticked. Three items: (1) ambiguous
  chat command in dev → assistant `ask` lands in the dock thread, (2)
  navigate via DateNavigator's next-day arrow → thread resets and a
  follow-up does NOT mutate the new day, (3) optional E2E (real LLM,
  cost): `node frontend/scripts/playwright/ai-chat-clarifying-question.mjs`
  + `ai-chat-date-change-resets-thread.mjs`. Plus the iOS Safari
  autogrow-textarea check from `docs/features/0007_PLAN.md` open note 3.
  Suggested by `claude-review` on PR #15.

- [ ] **Type hints on internal helpers in `backend/ai/views.py`.**
  `_consume_rate_limit`, `_log_interaction`, `_mark_success`,
  `_validation_error_detail`, `_check_*`, `_apply_*`, etc. lack full
  type annotations. Add them in a discrete refactor PR (or pair with
  a broader backend typing pass — the `schedules.api` and
  `templates_mgr.api` helpers have similar gaps). Out of scope for
  feature 0007 because it touches files unrelated to the chat surface
  and adds no behavioural change. Suggested by `claude-review` on PR #15.

- [ ] **`assertNumQueries` test for `select_related("daily_review")` in
  `ai_generate_draft`.** PR #15 added the `select_related` as a
  drive-by N+1 fix; the optimisation isn't covered by an explicit
  query-count test. Future regression risk: someone removes the
  `select_related` and tests still pass because the prompt builder's
  N+1 access doesn't break correctness. Add a test that seeds N past
  schedules each with a `DailyReview`, calls the draft endpoint with
  `run_draft` stubbed, and asserts `assertNumQueries(<expected>)`.
  Out of scope for feature 0007 because it tests a Phase-6 codepath.
  Suggested by `claude-review` on PR #15 iter 6.

- [ ] **PR #16 — defensive-runtime suggestions rejected as
  false-positives.** Five P2/P3 findings from `claude-review` on PR #16
  asked for runtime guards that contradict CLAUDE.md's "Don't add error
  handling for scenarios that can't happen" rule and the
  defensive-runtime entry in this file's false-positive catalogue:
  (1) `TEXTAREA_LINES[props.variant] ?? TEXTAREA_LINES.dock` fallback —
  TypeScript enforces the union, Vue's prop validator gates the
  boundary; (2) `typeof sidebarOpen.value === 'boolean'` check in
  `chatSidebarWidth` — the ref is typed `boolean` and initialised from
  a `boolean`-returning helper; (3) `if (typeof window === 'undefined')
  throw` in `useViewport` — the plan's Phase-1 design note explicitly
  rejects an SSR guard because Inertia renders client-side; (4) JSDOM
  unit tests for `autosize()` min/max clamps — `scrollHeight` is `0`
  under JSDOM (no layout engine), so any clamp test would assert
  against a degenerate value, not real browser behaviour; (5) `if
  (!target) return` in `handleGlobalKeydown` — `target?.tagName?.…`
  already optional-chains the null case and falls through to the
  no-op branch. Rejected per the iteration loop's P0/P1-only-deep-
  triage rule (skill docs § Step 6/7).

- [ ] **Remove the orphan `/api/ai/schedules/<date>/command/` endpoint
  and the `useAI` composable.** After feature 0007 (PR #15) `CommandBar.vue`
  routes through `useChat → /chat/`. The `/command/` view in
  `backend/ai/views.py` and `frontend/src/composables/useAI.ts` still
  exist; `useAI` is partially imported by
  `frontend/src/components/RegenerateDraftButton.vue` but only for the
  module-level shared state (`isProcessing`, `apiHealthy`), not for
  `submit()`. Touch points to delete cleanly: (a) backend view +
  URL route + dedicated tests, (b) `useAI.ts` whole file plus the
  `useAI()` import in `RegenerateDraftButton.vue` (refactor the spinner
  state to a shared module, or fold it into `useDraft.ts`), (c) any
  stragglers in `docs/api.md`. Filed in response to PR #20 `claude-review`
  P2 [QUALITY] finding — out of scope for the e2e-script cleanup PR
  because it crosses the backend/frontend boundary and changes a public
  API surface. Run the full `pytest backend/tests/` + `cd frontend &&
  npm test` and a chat-script smoke before merging.
