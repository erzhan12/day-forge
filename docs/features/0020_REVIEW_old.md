# Feature 0020 — Code Review: Todoist Integration (read-only task panel)

**Reviewed:** working tree vs `docs/features/0020_PLAN.md` (re-review after P1 fixes)  
**Review date:** 2026-06-18  
**Verification:** `uv run pytest backend/tests/test_todoist_sync_*.py -q` — **73 passed**; `npm test -- --run useTodoist TodoistTasksPanel useTodoistAccount` — **29 passed**

## Verdict

**Approve.** The prior P1 network-error bug is fixed and covered by tests. Phases 1–3 match the plan; backend and frontend mirror `calendar_sync` with the documented intentional divergences. No blocking or non-blocking correctness findings remain. One optional de-risk item (Phase 0 live filter spike) is still absent.

---

## P0 — Critical

None.

---

## P1 — Major

None.

### Resolved since prior review

**Network errors no longer set `connected = true`**

- **Fix:** `useTodoist.ts:134–136` gates `connected = true` on `result.status !== undefined`; no-status failures leave `connected` untouched while still setting `statusKnown` and surfacing the error.
- **Tests:** `useTodoist.test.ts` — `first-load network failure (no status) leaves connected=false` and `network failure does NOT revert an already-connected session`.
- **Lesson captured:** `tasks/lessons.md` documents the precondition-enumeration rule for status-gated UI state.

---

## P2 — Minor (non-blocking)

### 1. Phase 0 live filter spike still not implemented

**Plan ref:** `0020_PLAN.md` § Phase 0 (recommended, not required for V1)

`backend/tests/test_todoist_filter_spike.py` does not exist. Unit tests lock the **generated** query strings; Todoist's live interpretation of bare `YYYY-MM-DD` and `today | overdue` is unvalidated. Low risk given mocked tests and pinned algorithm; optional follow-up gated on `TODOIST_FILTER_SPIKE_TOKEN`.

### 2. Parallel `connected` writers can race (last-writer-wins)

**Files:** `Schedule.vue` (parallel `fetchAccountStatus` + `fetchTasks` on mount); `useTodoist.ts`

Same pattern as CalDAV. The network-error fix removes the worst failure mode; remaining race is edge-case on slow/flaky networks.

### 3. `fetchAccountStatus` in `useTodoist` ignores non-OK responses

**File:** `useTodoist.ts:167–171`

Masked in practice because `fetchTasks` always runs on mount. Same as `useCalendar.ts`.

### 4. No service-layer test for `ImproperlyConfigured` from decryption

View test mocks `fetch_tasks_for_date` with `ImproperlyConfigured`; no service test if `get_token()` were refactored inside the broad `except`. Same blind spot as CalDAV.

### 5. Settings connect/disconnect does not refresh Schedule composable

Pre-existing CalDAV / Inertia limitation; note for manual QA.

---

## P3 — Trivial nits

- `test_post_persists_encrypted_password` name kept as CalDAV analog (`test_todoist_sync_views.py:109` — comment explains).
- `useTodoistAccount.test.ts` has no `requestJson` GET/DELETE arg-shape regression test (covered for `useTodoist` only).

---

## Resolved polish from prior review

| Item | Status |
|------|--------|
| `set_token` docstring "events" → "tasks" | ✅ `models.py:37` |
| Timed-due `Z` / `+00:00` service tests | ✅ `test_todoist_sync_service.py:219–241` (parametrize) |
| Panel `aria-label` + header copy tests | ✅ `TodoistTasksPanel.test.ts:133–146` |

---

## Plan Compliance — Backend

| Requirement | Status |
|-------------|--------|
| `todoist_sync` app scaffold + migration | ✅ |
| `TODOIST_*` settings + import guards | ✅ |
| Model, crypto, checks E001/W001 | ✅ |
| Filter algorithm + pagination | ✅ |
| Priority mapping, due normalization | ✅ |
| Error hierarchy, cache, views, admin | ✅ |
| Wire: snake_case, `title` not `content` | ✅ |
| Per-task resilience, null-safe sort | ✅ |
| Token never logged | ✅ |
| Phase 0 live filter spike | ❌ (optional) |

---

## Plan Compliance — Frontend

| Requirement | Status |
|-------------|--------|
| Types, composables, panel, Schedule/Settings wiring | ✅ |
| GET `requestJson` footgun | ✅ |
| `connected=true` only on definitive HTTP statuses | ✅ (fixed) |
| `503 → connected=false`; abort/stale untouched | ✅ |
| `statusKnown` on every terminal `fetchTasks` path | ✅ |
| Dual commit guard; account serialisation lock | ✅ |
| Panel copy, CSS prefix, priority dots | ✅ |

---

## Plan Compliance — Docs

| Doc | Status |
|-----|--------|
| `.claude/rules/project.md` | ✅ |
| `RULES.md` | ✅ |
| `docs/api.md` | ✅ |

---

## Data Alignment

No issues. Todoist API `content` → wire `title`; account status has no token field; frontend types match `normalized_task_to_dict`.

---

## Over-Engineering / File Size

No concern. Mirrors `calendar_sync` without extra abstractions.

---

## Test Review

**Backend (73 tests):** Service, views, and checks mirror CalDAV templates. New since prior review: parametrize timed-due suffix cases (`Z`, `+00:00`, fractional `Z`, offset).

**Frontend (29 tests):** New since prior review: network-failure `connected` semantics (first-load + already-connected), panel header/`aria-label` assertion.

Tests are isolated (mocked HTTP / `requestJson`), fast (~11s backend, <1s frontend), and descriptively named.

---

## Optional follow-ups (not required for merge)

1. Add `test_todoist_filter_spike.py` gated on env token (or `docs/features/0020_spike.md`).
2. Service test for `ImproperlyConfigured` propagation from `get_token()`.
3. `useTodoistAccount` `requestJson` arg-shape regression test.
