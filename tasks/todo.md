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
