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

## Feature 0010 — Selectable Design Templates

Plan: `docs/features/0010_design_templates_PLAN.md`. Review: `docs/features/0010_REVIEW.md`.

### Phases

- [x] **P1 — Backend preferences data.** `UserPreferences` model + `Theme` TextChoices, migration `0003_user_preferences.py`, admin (`UserPreferencesAdmin` + `UserPreferencesInline` on `User`), `preferences.py` helper (frozen DTO, read-side normalization).
- [x] **P2 — Backend API + Inertia props + SSR.** `GET`/`PATCH /api/user/preferences/`, `_prefs_response` Cache-Control helper, `ui_preferences` prop + `template_data={"initial_theme": …}` on `schedule_view` / `settings_view` / `analytics_view`, `_render_login` helper for all three login render paths, `base.html` `data-theme="{{ initial_theme|default:'classic' }}"`.
- [x] **P3 — Frontend theme registry + composable.** `theme.ts` (`isKnownTheme` / `normalizeTheme` / `applyTheme`), `themes.ts` (registry + preview tokens), `useThemeFromProps`, `@inertiajs/core` `PageProps` augmentation, wiring in Schedule/Settings/Analytics, `Login.vue` defensive `applyTheme('strategic')`, `RULES.md` checklist.
- [x] **P4 — CSS token system.** `app.css` tokens for Classic, Strategic (radial gradient + inline-SVG turbulence), Light Premium. Token-name freeze observed.
- [x] **P5 — Settings selector.** `DesignSelector.vue` with radio group, single-source-of-truth (`page.props.ui_preferences.theme`), PATCH → `router.reload({only,onSuccess,onError,onFinish})`, all-three-disabled during save, `onError` fallback `applyTheme(normalizeTheme(id))` + `aria-live` warning, full a11y (Arrow nav, Space/Enter activation, `aria-disabled` on keyboard guard).
- [x] **P6 — Page/component theming pass.** 17 components + page shells migrated to `var(--…)` tokens via the shared P4/P6 checklist file list.
- [x] **P7 — Tests.** Backend 26 tests (DTO, normalization, PATCH happy/error/healing, Cache-Control on success + 400 paths, page-prop contract, hard-load SSR data-theme for login + parametrized authenticated pages, concurrent first-visit `TransactionTestCase`). Frontend 32 tests (`theme.test.ts`, `useThemeFromProps.test.ts`, `themeWiring.test.ts` static-scan, `DesignSelector.test.ts`). Playwright `theme-switch-persistence.mjs` with fail-closed JS-blocked SSR check.

### Cross-phase prerequisites

- [x] `base.html` `data-theme` wiring with `template_data=` on every `inertia_render` call site (P2).
- [x] `_render_login` helper enforces Strategic on all three login render paths (P2).
- [x] Category color contrast audit + per-theme hex overrides (P4 exit gate). Audit table in `categoryColors.ts` source comment; `health` overridden to `#059669` on Classic + Light Premium to clear 3:1 against panel surfaces. All other (theme, category) cells pass the base palette.
- [x] Unmounted-component guard in the Settings selector PATCH handler (`isMounted` flag set in `onBeforeUnmount`).
- [x] Drift-check `RULES.md` snippet vs final composable signature (matches current `useThemeFromProps()` import path and prop shape).

### 0010 follow-ups (post-merge)

- [ ] **0010-followup: user_preferences PATCH rate limit (v1.1).** Plan §Phase 2 deferred. Prerequisites: (a) extract a shared `backend/common/rate_limit.py` with sync + async entry points wrapping the same cache key scheme, (b) extend the `ai.E001` Django system check (or add a sibling) to cover any newly-registered bucket name via a registry, (c) add `USER_PREFERENCES_RATE_LIMIT_PER_HOUR` env var and wire the PATCH handler. Reason for v1 deferral: endpoint is authenticated + CSRF-protected + low-volume; worst-case abuse is one user thrashing their own preference row.
- [ ] **0010-followup: category contrast audit re-verification after Strategic font swap.** If/when a self-hosted variable serif lands for Strategic display headings (v1.1 path in plan §Phase 4), re-run the contrast audit — heavier serif strokes may shift effective contrast on small text adjacent to category swatches.
- [ ] **0010-followup: split `templates_mgr` if a second preference field is added.** When a second non-template preference lands (notifications, locale, time format, etc.), promote `UserPreferences` to a dedicated `users` or `preferences` app to avoid the junk-drawer pattern. Plan §Phase 1 forward-pointing note.
- [ ] **0010-followup: Strategic editorial serif (Fraunces / Playfair Display / Source Serif 4).** v1 ships Georgia stack which under-delivers the editorial feel that motivated the Strategic theme. Pre-approved path: self-hosted OFL variable serif, subset Latin + Cyrillic, woff2 ~50–80 KB, served from `frontend/public/fonts/` via Vite — no CDN dependency. Update `--font-family-display` under `html[data-theme="strategic"]` only.
- [ ] **0010-followup: link `theme-switch-persistence.mjs` from the feature manual-test doc.** The persistence + fail-closed FOUC script is on disk but not yet referenced in any `docs/features/*_MANUAL_TEST.md`. When a `0010_MANUAL_TEST.md` is written (or 0008's gets re-flowed), add it to the script index alongside the `ai-*.mjs` entries.
- [ ] **0010-followup: `BroadcastChannel("ui_preferences")` for cross-tab convergence (v1.1 if needed).** v1 accepts per-tab serialization + cross-tab last-write-wins (loser tab self-heals on next navigation). Plan §Phase 5 cross-tab scope statement. Don't ship without a demonstrated need — theme switching is a low-frequency action.
- [ ] **0010-followup: Cache-Control on 405/302 from preferences endpoint.** Plan §Phase 2 literal bullet listed 405/302 in the no-store list. Implementation does not cover them — Django's `@require_http_methods` / `@login_required` decorators run before the view so the helper never sees those paths. Practical risk is nil (405 body is empty, 302 has no body, no per-user state leak surface) — retrofit would need middleware. Currently documented in `_prefs_response` docstring + `docs/api.md` + pinned by three tests as accepted-delta behavior. If a future requirement is strict compliance, flip the assertions in `test_unauthenticated_get_302_has_no_cache_control_header` / `..._patch_302_...` / `test_method_not_allowed_405_...` and add the middleware.

- [ ] **0010-followup: extract a `useIsMounted()` composable.** `DesignSelector.vue` uses a `let isMounted = true` + `onBeforeUnmount(() => isMounted = false)` pattern in ~4 callback sites to guard against post-unmount mutations from `router.reload` callbacks. The pattern would also fit any future component that wires async navigation callbacks. Premature to extract for a single consumer — wait until a second consumer needs the same guard, then refactor to `frontend/src/composables/useIsMounted.ts` returning `() => boolean` so callers do `if (!isMounted()) return`. Don't preempt; the inline pattern is fine for v1.

- [ ] **0013-followup: explicit `useNowMinutes` wiring assertion in `SkippedTasks.test.ts`.** Existing tests already exercise the composable via behaviour ("list grows when interval advances past block end") but never directly assert `SkippedTasks.vue` subscribes to `currentHHMM`. Adding a focused mock-and-verify test would harden against a future refactor that accidentally drops the `useNowMinutes` call. Deferred from claude-review on PR #36 — current coverage proven adequate by the existing suite passing across all the day-boundary scenarios in `useNowMinutes.test.ts`.

- [ ] **0014-followup: add `"false"` to the `test_non_dict_json_body` parametrize list.** Plan §Fix listed five non-dict literals (`[]`, `"x"`, `123`, `null`, `true`); `"false"` hits the same guard branch but was deliberately omitted to mirror the plan exactly and to match `test_ai_views_chat.py::test_non_object_json_root_returns_400`'s five-case list. Suggested by claude-review on PR #39 as a P3 polish; apply if/when the chat counterpart is also broadened so the two surfaces stay in lockstep.

- [ ] **0014-followup: strengthen `test_invalid_json_body` to assert the exact `"Invalid JSON."` body.** Pre-existing gap surfaced by claude-review on PR #39 — the sibling test for malformed-but-non-empty JSON asserts only `status_code == 400`, not the error envelope. The new `test_non_dict_json_body` is stricter (asserts exact `errors.body` string); aligning the older test would match that pattern. Trivial single-line change; deferred to keep PR #39 minimal and scope-pure.

## Follow-ups (discovered during manual testing)

### External calendar

- [ ] **Overnight external events fade as "past" while still running
  (pre-existing, surfaced during the feature 0026 review).**
  `frontend/src/utils/externalEventPast.ts` compares only the *clock* minutes
  of `ev.end` against `nowMinutes`, with no day-delta fold. An event running
  `23:00 → 00:30 (+1 day)` has an end whose local wall-clock is `00:30` = 30
  minutes, so from 00:30 onward on the viewed day the row renders faded even
  though the event is ongoing or still upcoming. Same UTC→local class of bug
  that `computeEventBlockTimes` was written to avoid, in the panel that owns
  the Add button. **Not touched by feature 0026** — the file predates it and
  is unmodified on that branch, so it was left alone to keep that PR scoped.
  Fix needs the same viewed-day anchoring `travelRules.ts` uses.

- [ ] **0026-followup: Playwright smoke for the add-to-schedule flow.**
  Script the add paths end-to-end in `frontend/scripts/playwright/`: add with
  no rule (exact event times), add with a 30/30 rule (−30/+30), dialog
  override wins over the matched rule, overlap returns the `errors.time`
  message unchanged, re-add of the same event to a free slot. No LLM calls —
  hits only calendar/schedule endpoints. Plus the off-grid lifecycle
  (complete/rename/drag/undo on a `14:07–14:33` block) and reorder direction,
  which are the highest-risk paths unit tests can't cover. Until this exists,
  those paths are covered only by the manual smoke checklist. Raised by
  claude-review on PR #99.

- [ ] **0026-followup: atomic reorder swap for rule lists.**
  `TravelRulesList.bumpOrder` (and the pre-existing `RulesList.bumpPriority`
  it mirrors) reorders by two sequential `updateRule` PATCHes with no
  atomicity — a first-succeeds / second-fails sequence leaves two rows with
  the same `order`. Self-corrects on the next successful reorder and the
  equal-order branch nudges by ∓1, so it is not user-blocking. Accepted gap
  in `docs/features/0026_REVIEW.md`. If it becomes user-visible, add one
  dedicated atomic swap endpoint and point both components at it (fixing them
  together avoids re-diverging the two siblings). Raised by claude-review on
  PR #99.

### Static assets / icons

- [ ] **0025-followup: decide the fate of the three unlinked icon assets.**
  `icon-192.png`, `icon-512.png` and `logo-full.png` total 329 KB and ship with
  no `<link>` tag, no web app manifest, and no UI reference — they only enlarge
  the `collectstatic` corpus and the production image. Either land the PWA
  manifest (which gives 192/512 a purpose) and the login-page header (which
  gives `logo-full` one), or drop the files and re-add them with the PR that
  uses them. Raised by claude-review on PR #98.

- [ ] **0025-followup: record the icon set's provenance.** `RULES.md` says no
  master is committed, but gives no pointer to the original Midjourney artwork
  (prompt text, job ID, or account), so regenerating the icons is currently
  blocked on whoever generated them. Needs the original author to supply the
  details — then either commit the master under `docs/assets/` or note the job
  reference in `RULES.md`. Raised by claude-review on PR #98.

- [ ] **0025-followup: consider serving a real `favicon.ico` at the web root.**
  Some crawlers, headless clients and link-checkers `GET /favicon.ico`
  unconditionally regardless of `<link rel="icon">`, producing 404 log noise.
  Only a genuine `.ico` at the root fixes this — adding
  `rel="shortcut icon"` pointing at a PNG does not, since those clients never
  parse the HTML. Zero user-visible impact on supported browsers, so this is
  log hygiene only. Raised by claude-review on PR #98.

### Drag / Undo

- [ ] **useDrag abort feedback.** When `blocksExternallyMutated` detects a concurrent mutation during drag, `endDrag` aborts silently (no toast) — consistent with `cancelDrag()`. Adding user feedback requires wiring a toast callback into `useDrag` (see `UndoToast.vue` for the pattern). Defer until user-reported confusion surfaces. Tracked per comment at `frontend/src/composables/useDrag.ts:413-415`.

### UX / Rules

- [x] **Shorten oversized leading gap at top of timeline.** Done in feature
  0017 (Approach A — origin-shift linear render): leading *and* trailing edge
  gaps collapse to fixed `STUB_MINUTES` (30-min / ~60px) compact stubs while
  the timeline stays linear in minutes. The stub remains a click-to-add
  `GapSlot` emitting the full semantic range, preserving the early-morning add
  affordance. See `docs/features/0017_compact_timeline_stubs_SPEC.md`. Original
  note below for context. When the first
  block starts well after `DAY_START` (06:00), `displayList` renders a
  full-height leading `GapSlot` from 06:00 to the first block
  (`frontend/src/pages/Schedule.vue:259-268`) at `PX_PER_MINUTE = 2`
  (`frontend/src/utils/scheduleTime.ts:8`) — e.g. a 09:00 first block
  yields 360px of empty space before any content. Shorten it. Design
  under discussion (collapse to compact stub vs. derive timeline start
  from earliest block vs. configurable day start). Constraint: the
  leading gap is an interactive `GapSlot` (click-to-add), so any
  collapse must preserve the early-morning add affordance.

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

- [ ] **`frontend/scripts/playwright/README.md`.** As of PR #27 we
  have 10 e2e scripts (6 chat + 2 command + 2 draft); deferred earlier
  as "premature for 2". Add a short README documenting: prereqs
  (Django + Vite + ``playwright`` test user creation snippet), how to
  run individual scripts, expected cost/duration per script (some make
  real LLM calls, the 409 draft script short-circuits), and shared
  assumptions (seed dates, idempotent setup, etc.). Pair with the
  Makefile follow-up above. Suggested by `claude-review` on PR #11,
  PR #13, and PR #27.

- [ ] **Extract magic numbers in playwright scripts.** `await page.waitForTimeout(1500)`,
  the 30-iteration login wait loops, etc. Pull out as named
  `WAIT_FOR_PATCH_MS` / `LOGIN_POLL_MAX_TRIES` / etc. Trivial
  readability cleanup. Suggested by `claude-review` on PR #13 and
  PR #27 (more urgent now that 10 scripts share inconsistent values).

- [ ] **N+1 regression test for draft history.** `ai-draft-on-empty-day.mjs`
  has a `// TODO: N+1 sanity` comment because capturing Django SQL
  during a request from a Playwright harness needs either DEBUG=True
  + SQL log capture or a connection-instrumented harness. Cover this
  with a backend pytest using `django.test.utils.CaptureQueriesContext`
  on `/generate-draft/` with `LLM_HISTORY_DAYS=3`: assert the
  `analytics_dailyreview` query count is 1, not N. The original
  N+1 fix was PR #15 (`select_related("daily_review")` in the draft
  history query). Suggested by `claude-review` on PR #27.

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

- [ ] **Explicit regression test for `_Rollback` propagation across
  `sync_to_async`.** PR #22 `claude-review` iter-2 P2 [TESTING] flagged
  this. Currently the `_Rollback` exception path through
  `await sync_to_async(_apply_actions_sync, thread_sensitive=True)(...)`
  is covered *implicitly* by `test_mid_batch_failure_rolls_back` in
  `test_ai_views.py` and the analogous draft / chat tests — each
  asserts a 400 / 409 response after an action error mid-batch, which
  can only land if the exception crossed the thread boundary cleanly.
  An explicit test (e.g. unit-level: call `_apply_actions_sync` from
  an `async def` test body via `sync_to_async`, raise `_Rollback`
  inside, assert it surfaces with the stashed `JsonResponse` intact)
  would document the asgiref re-raise contract directly. Low priority
  — defense-in-depth; the implicit coverage already catches a
  regression. Pin if the contract ever changes (e.g., asgiref version
  bump that affects exception propagation) or if a future bug actually
  shows the implicit tests missing something.

- [ ] **CalDAV: drop-counter / metrics for malformed VEVENT skips.**
  PR #30 `claude-review` iter-1 P1 [QUALITY] flagged
  `backend/calendar_sync/service.py:_normalize_vevent`'s broad
  `except Exception` — it logs each failure but provides no aggregate
  visibility. The project has no metrics infra (no Prometheus / StatsD
  sink), so a bare `counter += 1` would be dead code. Defer until
  either a metrics surface lands or a real-world incident shows the
  per-event logs are noisy enough to need aggregation. Cheap
  alternative when it comes up: emit a single `logger.warning` summary
  per-fetch with `(drops, total)` counts.

- [ ] **CalDAV: concurrent `POST /api/calendar/account/` regression
  test for the same user.** PR #30 `claude-review` iter-1 P2 [TESTING]
  asked for a threaded test that two simultaneous POSTs serialize
  cleanly via the `select_for_update` + `get_or_create` flow in
  `calendar_sync/views.py:account`. SQLite (Day Forge's dev DB) only
  weakly honours `SELECT ... FOR UPDATE` — `schedules.W001` already
  warns about this — so a threaded test would be flaky on SQLite and
  meaningful only against Postgres. Pin to whichever PR moves
  `schedules` to a real concurrency-supporting DB (probably the same
  PR that satisfies `schedules.W001`); add the test alongside any
  other deferred concurrency coverage.

- [ ] **CalDAV admin: at-a-glance "connected" column.**
  PR #30 `claude-review` iter-1 P3 [DOCS] suggested adding a
  `connected_status` field to `CalDAVAccountAdmin.list_display` that
  renders "✓ Connected" or empty. Cosmetic; the existing columns
  (`user`, `apple_id`, `base_url`, `last_verified_at`) already convey
  the same info. Pin when an ops person actually reports needing it.

- [ ] **CalDAV: debug-only `?nocache=1` query param on
  `GET /api/calendar/events/<date>/`.** PR #30 `claude-review` iter-1
  P3 [QUALITY] suggested a dev-only escape hatch that bypasses
  `get_cached_events`. Useful for the rare "events not updating"
  debug session, but adds API surface and a `DEBUG` branch in a path
  with no current production user-complaints. Pin when a real
  debugging incident calls for it.

- [ ] **CalDAV: `LLM_*`-style per-user rate limit on `/api/calendar/*`.**
  PR #30 `claude-review` iter-2 P1 [SECURITY] flagged the absence of a
  `CALDAV_RATE_LIMIT_PER_HOUR` bucket on `calendar_sync/views.py`. The
  server-side per-(user, date, account.updated_at) cache absorbs the
  common-case abuse (repeat fetches of the same day), and cache-miss
  spam is bounded by the number of distinct dates a single user can
  enumerate. No measured iCloud throttling complaint exists today, so
  the work is deferred rather than scope-crept into the V1 PR. Pin if
  iCloud starts rate-limiting Day Forge, or if a real abuse pattern
  surfaces in the audit log. Implementation reference: mirror
  `ai/views.py:_consume_rate_limit` with a fresh `caldav_rl` bucket
  and update `ai.E001` (or split into `calendar_sync.E002`) to cover
  the new bucket under the same LocMemCache prod guard.

- [ ] **CalDAV: cache the `Fernet(key)` instance.** PR #30
  `claude-review` iter-2 P2 [PERFORMANCE] suggested an
  `@lru_cache(maxsize=1)` on `_fernet()` in
  `backend/calendar_sync/crypto.py`. The constructor cost is
  microseconds (base64 decode + key length check); no measured hot
  path. Naive `lru_cache` would also leak across `override_settings`
  test contexts unless the cache is keyed on the settings value. Pin
  when a measured-hot-path complaint surfaces or when the encrypt /
  decrypt call rate climbs (e.g., bulk re-key migration).

- [ ] **CalDAV: edge-case regression tests for iCalendar surface.**
  PR #30 `claude-review` iter-4 P3 [TESTING] asked for three explicit
  test cases: (a) VEVENT with DURATION but no DTEND, (b) recurring
  events with EXDATE exclusions, (c) events spanning DST transitions.
  The broad `_normalize_vevent` + `_expand_events` catch lists already
  protect against malformed inputs from these paths, but explicit
  regression tests would lock in the parse contract for the
  recurring-ical-events lib. Defer because: (a) requires constructing
  a DURATION-only VEVENT, exercising the existing fallback path in
  `_normalize_vevent`; (b) requires a real EXDATE fixture that
  recurring_ical_events knows how to exclude; (c) requires a tz like
  America/New_York and a date around 2026-03-08. Cheap individually
  but they're test scaffolding work; pin if/when the upstream lib
  ships a breaking change to the expansion API.

- [ ] **CalDAV: ERROR-level escalation for repeated malformed-event
  drops within one fetch.** PR #30 `claude-review` iter-4 P2 [QUALITY]
  suggested escalating from `logger.warning` to `logger.error` when
  > 5 events fail to normalize in a single fetch, on the theory that
  isolated corruption is noise but systemic corruption is signal.
  Requires a per-fetch counter passed into `_normalize_vevent` /
  `_expand_events`. Defer until either iCloud throws a known
  corruption pattern at us in the audit log, or the project gains a
  metrics-emission infra (see also: iter-1 P1 [QUALITY] deferral
  above for the drop-counter / metrics work).

- [ ] **Export `PLACEHOLDER_ROTATION_MS` from CommandBar.vue so tests don't hardcode it.**
  Currently `frontend/tests/CommandBar.test.ts` hardcodes `6_000` independently of the
  component constant. In Vue SFCs with `<script setup>` a named export requires a
  separate `<script>` block — structural change, low priority since the value is stable.
  Suggested by `claude-review` on PR #55 (P3 [QUALITY]).

### Todoist (feature 0020) — PR #63 review deferrals

- [ ] **Rate-limit the account-connect endpoints (CalDAV + Todoist).**
  `claude-review` on PR #63 flagged `POST /api/todoist/account/` as having
  no rate limit (token brute-force). Deferred, not blocking: the endpoint
  is `@login_required`, the brute-force target is Todoist (which rate-limits
  itself), and `POST /api/calendar/account/` has the same absence — so this
  is a pre-existing pattern, not introduced by 0020. If added, do it
  symmetrically for both providers (a shared `connect_rl:<user_id>` fixed
  window mirroring `ai_cmd_rl`, env `*_CONNECT_RATE_LIMIT_PER_HOUR`,
  documented in `.claude/rules/project.md`, returning 429).

- [ ] **De-duplicate `extractErrorMessage` across composables.** Identical
  helper in `useTodoist.ts` and `useTodoistAccount.ts` (and the CalDAV
  analogs). Extract to a shared `frontend/src/composables/useHttp.ts` export
  or `utils/errors.ts`. Multi-file refactor that should also fold in the
  CalDAV copies — its own small PR. (`claude-review` PR #63, P2 [QUALITY].)

  > Explicitly NOT doing (rejected on PR #63 with rationale): a pagination
  > truncation cap (contradicts the plan's "fetch all, never truncate"),
  > caching the `Fernet` instance (breaks runtime key rotation), and
  > "zeroing" the decrypted token string (CPython strings are immutable —
  > the rebind is ineffective security theater).

- [ ] **Integration test for displayList's frozen-now wiring in
  Schedule.vue.** `Schedule.test.ts` mocks `useDrag` entirely, so the
  feature-0023 geometry-freeze expression in the `displayList` computed
  (`frozenBounds ? frozenNowMinutes.value : todayNowMinutes.value`) has no
  component-level coverage — a regression to live `todayNowMinutes` would
  make the idle/tail split boundary jump on each 60s tick mid-drag. Needs a
  mount harness that drives real drag state (un-mock `useDrag` or expose the
  computed), which is its own design decision — deferred as its own task.
  The pure-function halves are unit-covered (`frozenNowMinutes` lifecycle in
  `useDrag.test.ts`; split-boundary maths in `scheduleTime.test.ts`).
  (`claude-review` PR #94, P2 [TESTING].)

- [ ] **Manual smoke pending (feature 0023):** click-to-add on the new
  full-scale idle gap on today — verify the add-dialog pre-fills with
  `[lastEnd, now)` per `docs/features/0023_PLAN.md` § "Manual smoke".

- [x] **App logo / favicon (feature 0025):** icon-only crop of the
  Midjourney logo added to `frontend/public/` as favicons (16/32/48),
  apple-touch-icon (180), and PWA-ready icons (192/512 — shipped but
  *not* linked, no webmanifest exists yet). Only the four favicon /
  apple-touch assets get `<link>` tags, added to both dev/prod branches
  of `base.html` and pinned by `backend/tests/
  test_base_template_icons.py`. Dev serving + prod build verified.
- [ ] **Manual smoke pending (feature 0025):** load
  http://localhost:5173/ with the dev stack up — browser tab shows the
  anvil icon; optionally decide whether `logo-full.png` should appear on
  the Login page.

- [ ] **Section nesting nit (feature 0028, PR #108 P3):** `DesktopNotificationToggle.vue`
  renders a `<section class="desktop-section">` root that `Settings.vue` wraps
  in `<section class="section">`, producing `section > section`. Deferred, not
  fixed: this mirrors the pre-existing `SoundNotificationToggle.vue` structure
  the plan mandated mirroring — changing desktop-only would diverge from the
  sibling. If reworked, do BOTH toggles together (root → fragment/div, keep
  `aria-labelledby` on the inner `<h2>`) so the pair stays consistent.

- [ ] **Dismissed-vs-denied hint copy (feature 0028, PR #108 P3):** the
  `"default"` permission result (user dismissed the prompt without deciding)
  currently shows the same "Browser blocked… allow in site settings" hint as an
  explicit `"denied"`. Plan-mandated for MVP (`denied/default ⇒ permissionDenied`),
  so deferred. Future copy/i18n pass: add a `permissionDefault` flag →
  "Click again to re-request notification permission."
