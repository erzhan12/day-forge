---
paths:
  - "backend/schedules/mutations.py"
  - "backend/schedules/commands.py"
  - "backend/schedules/planning.py"
  - "backend/schedules/persistence.py"
  - "backend/schedules/window.py"
  - "backend/schedules/models.py"
  - "backend/schedules/api.py"
  - "backend/schedules/http.py"
  - "backend/schedules/reads.py"
  - "backend/schedules/views.py"
  - "backend/schedules/validators.py"
  - "backend/schedules/time_validation.py"
  - "backend/schedules/serialization.py"
  - "backend/schedules/settings_api.py"
  - "backend/schedules/provenance.py"
  - "backend/schedules/admin.py"
  - "backend/schedules/categories.py"
  - "backend/schedules/category_api.py"
  - "backend/schedules/category_palette.py"
  - "backend/schedules/migrations/**"
  - "backend/tests/test_schedule_*.py"
  - "backend/tests/test_time_*.py"
  - "backend/tests/test_timeblock_*.py"
  - "backend/tests/test_undo_*.py"
  - "backend/tests/test_restore.py"
  - "backend/tests/test_policy_mutation_lock.py"
  - "backend/tests/test_reads.py"
  - "backend/tests/test_reorder.py"
  - "backend/tests/test_views.py"
  - "backend/tests/test_models.py"
  - "backend/tests/test_status_flow.py"
  - "backend/tests/test_block_*.py"
  - "backend/tests/test_categories.py"
  - "backend/tests/test_timezone_*.py"
  - "backend/tests/test_user_local_helpers.py"
  - "frontend/src/composables/useSchedule*.ts"
  - "frontend/src/composables/useDrag.ts"
  - "frontend/src/composables/useMutationUndo.ts"
  - "frontend/src/composables/useUndo.ts"
  - "frontend/src/composables/useNowMinutes.ts"
  - "frontend/src/composables/useBlockCompletion.ts"
  - "frontend/src/pages/Schedule.vue"
---

## Schedule writes and revisions

- `backend/schedules/mutations.py` is the boundary for supported schedule writes. Manual create, import, PATCH, DELETE, reorder, restore, AI chat, draft generation, and review changes use `execute_schedule_mutation`. Policy and maintenance writers use its User lock or the maintenance entry points. Admin schedule, block, settings, rule, and template views are inspection only. Fixtures and migrations may use direct ORM writes.
- Client writes supply `expected_revision`. A missing, invalid, or stale value returns a controlled `409 schedule_changed`; do not silently substitute the current version. The transaction locks User, Schedule, then TimeBlock. Its initial User write reservation serializes SQLite writers, and the conditional revision update rejects stale writes. SQLite busy or locked retries the whole transaction at most three times. A callback must contain only database work that can roll back. Keep `OperationalError` unwrapped until the executor handles it.
- Scope reads and writes to the authenticated user. A foreign block, category, template, or rule ID returns 404 rather than disclosing ownership. Schedule writes also carry the captured user identity; a session mismatch returns `401 session_invalid` before mutation. Login redirects are invalid sessions, while an ordinary 403 remains a rejected request.
- Increase a day's revision once when its blocks or status actually change. Identical writes preserve revision and status. Notes and AI audit rows do not advance it. Capture schedule, ordered blocks, and revision within the accepted transaction; never attach a post-commit block read to an older revision. Multi-day maintenance processes schedules in stable ID order. Category reassignment that changes a day advances that day's revision.
- A fully bootstrapped Schedule GET captures schedule, ordered blocks and page policies in one read transaction. It must not reserve the SQLite writer through `UPDATE User`. Missing first-use rows use the shared writer lock, capturing both the creation flag and page snapshot before commit. Only the request that creates Schedule may emit the one-shot auto-draft signal. Exhausted contention inside the page view returns 503 with `Retry-After: 1`; it does not hide unrelated database errors.
- `backend/schedules/commands.py` owns mutation value types and has no database access. `planning.py` applies commands to candidate values, validates the complete final state, and computes the diff. `persistence.py` writes an accepted diff. `mutations.py` owns the locking executor and retry loop. Keep these boundaries: validate interval order and overlaps before persistence, and keep database writes inside the executor. Intervals are half-open, so adjacent blocks may touch. The database constraint `timeblock_start_lt_end` protects direct writes. Do not add per-row `full_clean()` to supported mutation paths or hide SQLite busy errors inside a persistence exception.
- Forward user edits with a non-empty diff move a draft or reviewed day to active. Draft generation and Undo preserve day status. An active day can be marked reviewed; a draft day cannot. `mark_active_on_edit()` uses a conditional database UPDATE on persisted status, because an in-memory model instance may be stale. A same-value AI action and an empty chat action list preserve status and revision after context checks.

## Validation by source

| Source | Boundary and window policy | Failure scope |
| --- | --- | --- |
| Manual create or edit | New or changed edges use the five-minute grid. Changed edges can clamp to the configured window; an interval entirely outside it is rejected. Unchanged imported edges survive. | Reject the operation. |
| Calendar event import | Off-grid minutes are allowed. Clamp both edges to the window. | Reject the operation. |
| AI chat | Check explicitly supplied edges on the grid. Preserve inherited edges. Derived duration or move ends cannot be silently clamped. | Reject an impossible timing change; independent metadata may still apply. |
| Draft | Require grid-aligned explicit edges inside the window. | Reject the whole draft. |
| Undo restore | Restore original minutes, including off-grid edges and values outside the current window. | Reject invalid intervals or overlap for the whole snapshot. |

`get_schedule_window(user)` resolves the configured bounds; `DEFAULT_WINDOW` is a default, not runtime policy. Stored block times are local `HH:MM` values without a UTC offset. The configured IANA zone is stored on `UserScheduleSettings.time_zone` and exposed through `schedule_window.time_zone`. Day and clock calculations use that setting. A 23- or 25-hour daylight-saving day still has local wall times, so repeated-hour instants cannot be distinguished by a TimeBlock alone. See `backend/schedules/window.py`, `frontend/src/composables/useNowMinutes.ts`, and [R06](../../docs/REFACTORING_R06.md).
