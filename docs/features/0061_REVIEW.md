# Feature 0061 — External Code Review Trail

Fix for issue #161: `block_detail` PATCH now rejects non-object / oversized JSON
bodies before any membership check or DB mutation, mirroring sibling endpoints.

## External review trail

- **Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`agent --mode ask`).
- **Change surface:** `backend/schedules/api.py`, `backend/tests/test_views.py`,
  `docs/api.md`.
- **Rounds:** 1.

### Findings

| # | Engine | Severity | Verdict | Evidence |
|---|--------|----------|---------|----------|
| — | codex | NO P1/P2, no P3 | — | Full suite 1097 passed (2 errors were sandbox temp-dir artifacts in `test_ai_service_draft`, unrelated to this change); focused `TestBlockDetail` 26 passed; ruff + `git diff --check` clean. |
| 1-4 | cursor | P3 | **REJECTED — off-target** | All four cite `frontend/src/lib/notify.ts`, `QuickCapture.tsx`, `Reviews/Show.tsx` (feature 0033 background-notifications). None of those files are in this change surface; cursor reviewed the wrong changeset (network-retry storm, task exited 144). No claim maps to `api.py` / `test_views.py` / `docs/api.md`. |

- **Findings:** raised 4, accepted 0, rejected 4 (all off-target / wrong feature), P3-ignored 0.
- **Verification:** `uv run ruff check backend/schedules/api.py backend/tests/test_views.py` clean;
  `uv run pytest backend/tests/test_views.py::TestBlockDetail -q` → 26 passed.
- **Result:** SUCCESS — zero valid P1/P2, tests + lint green.
