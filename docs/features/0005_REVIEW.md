# Phase 5 Code Review

Reviewed against `docs/features/0005_PLAN.md` and `commands/code_review.md`.

## Findings

No open findings after the follow-up fixes.

### Resolved: Draft apply did not lock the empty schedule row before inserting blocks

- **Previous severity:** High
- **File:** `backend/ai/views.py:653`
- **Status:** Resolved. The apply phase now opens `transaction.atomic()`, calls `Schedule.objects.select_for_update().get(pk=schedule.pk)`, and only then re-checks `TimeBlock` emptiness before applying draft actions.
- **Regression coverage:** `backend/tests/test_ai_views_draft.py::TestApplyLocksScheduleRow::test_locks_schedule_row` spies on the `Schedule` manager and asserts the parent-row lock path is used. This is the right shape for SQLite-backed tests, where `FOR UPDATE` is stripped from SQL.

### Resolved: Invalid draft requests consumed the draft rate-limit budget

- **Previous severity:** Medium
- **File:** `backend/ai/views.py:598`
- **Status:** Resolved. Draft rate-limit consumption now happens inline after body-size validation, date parsing, empty-schedule check, and template lookup. The command endpoint still uses the decorator, while the draft endpoint consumes `ai_draft_rl:*` only once it is about to attempt the LLM call.
- **Regression coverage:** `backend/tests/test_ai_views_draft.py::TestRateLimitDoesNotFireOnPreconditionFailure` covers `422`, `409`, invalid dates, and oversized bodies staying at counter value `0`, while provider failure increments the counter as expected.

## Plan Coverage Notes

- Per-user `Template` / `Rule` ownership, unique `(user, type)`, seed scoping, admin visibility, settings page, template/rule CRUD, draft prompt/service/schema additions, draft endpoint, status flip rules, Inertia props, draft UI, regenerate button, and partial reload updates are implemented.
- The API response nesting for `GET /api/templates/` and `GET /api/rules/` is consistent across backend, docs, tests, and frontend composables (`{templates: [...]}` / `{rules: [...]}`), even though the plan sketch showed bare arrays.
- Tests cover happy paths and many edge cases for template/rule CRUD, draft generation, provider errors, rate-limit separation, status flow, parent-row locking during draft apply, and the "precondition failures do not consume draft budget" contract.
- No obvious over-large file issue stood out for Phase 5. `backend/ai/views.py` is getting dense, but the new draft code reuses existing helpers and is still navigable.

## Verification

- `uv run ruff check backend/` — passed
- `uv run pytest backend/tests/test_ai_views_draft.py -q` — passed (`20 passed`)
- Prior full-run baseline from the previous review remains: `uv run pytest backend/tests/ -q` passed (`216 passed`), `cd frontend && npx vue-tsc --noEmit` passed, and `cd frontend && npm test -- --run` passed (`82 passed`).
