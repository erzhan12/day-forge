# Feature 0044 — Code Review Trail

Removal of the orphan `/command/` AI endpoint + the `useAI` composable (cross-boundary
deletion of a public API surface), after feature 0040 migrated the async-boundary
regression coverage to backend pytest. Plan: `docs/features/0044_PLAN.md` (passed
plan-debate ×4 + ext-plan-review ×4).

## Pre-review ground-truth (implementation gates)
- `uv run pytest backend/tests/ -q` → **872 passed**
- `uv run ruff check backend/` → clean
- `uv run python backend/manage.py check` → clean (**ai.E001 still fires for draft+chat**)
- Canonical stale-reference grep → **0** live hits
- `cd frontend && npm test` → **707 passed**; `npx vue-tsc --noEmit` → clean

## External review trail

**Engines:** OpenAI codex (`gpt-5.6-sol`, read-only) + Cursor agent (`--mode ask`), parallel.
**Rounds:** 1.
**Change surface:** 41 files — whole-file deletions (`test_ai_views.py`, `test_ai_service.py`,
`useAI.ts`, `useAI.test.ts`, `scripts/test9_rate_limit.py`, 3 `ai-command-*.mjs`), new migrated
tests (`test_ai_apply.py`, `test_ai_service_client.py`), backend/frontend/docs/config edits.

Cursor returned **NO P1/P2 on production KEEP/DELETE correctness or shared-apply coverage loss**
(verified the migrated pins match the plan's must-keep matrix; the mid-batch overlap case is a
plan-phase reject with real mid-persist rollback still pinned by
`test_persist_validation_error_rolls_back_with_action_index` + `test_mark_active_failure_rolls_back_diff`).

### Findings (deduped)

| # | Sev | Finding | Verdict |
|---|-----|---------|---------|
| 1 | P2 (codex) | Chat rate-limit test (`test_ai_views_chat.py` `TestRateLimit`) pinned only status+counter; the deleted command test also pinned that a 429 short-circuit writes **no** `AIInteraction` row (a KEEP-path contract). | **ACCEPTED, FIXED** — added `AIInteraction.objects.count() == 1` + 429 error-body assertion. |
| 2 | P2 (codex) | `run_chat`'s real `result.explanation` extraction (`service.py`) was unasserted — all view tests mock `run_chat`; the migrated service success test didn't assert `explanation`. | **ACCEPTED, FIXED** — added `assert result.explanation == "ok"` in `test_ai_service_chat.py::test_returns_chat_result_with_actions`. |
| 3 | P2/P3 (both) | Stale **bare-word** references the canonical grep can't catch (`/command/` regex ≠ "command endpoint" / "e2e-command" / "one-shot command" / non-existent `_scheduleChanged()` / "three endpoints" / deleted-test-file paths) across `RULES.md`, `CLAUDE.md`, `README.md`, `docs/api.md`, `conftest.py`, `test_ratelimit.py`, `test_ai_views_chat.py` docstring, `tasks/todo.md`. | **ACCEPTED, FIXED** — grepped the full bare-word set repo-wide and scrubbed all; residual grep now clean. |
| 4 | P3 (codex) | `test_ai_views_chat.py` grew to ~1,271 lines after the migrated `TestSharedApplyCoverage` class; could split into a dedicated module. | **Recorded, not fixed** — organizational; non-blocking. |

No findings rejected. Cursor's mid-batch concern was already covered (no action needed).

### Verification (after fixes)
- `uv run pytest backend/tests/test_ai_service_chat.py test_ai_views_chat.py test_ratelimit.py -q` → **84 passed**.
- `uv run ruff check backend/` → clean.
- Residual bare-word stale-ref grep → **0**.

### Result
Two P2 coverage gaps in the migrated tests fixed; the bare-word doc-scrub class closed repo-wide;
one P3 (file size) recorded. **SUCCESS.**
