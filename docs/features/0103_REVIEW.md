# Feature 0103 — Code Review Trail

Fix issue #103: `create_block` 500s on malformed JSON field types. Type
guards mirror `create_block_from_event` (oversized-body 413, non-object
body 400, `isinstance(..., str)` for times/title/category — no shared
helper, per issue out-of-scope boundary).

## External review trail

**Engines:** OpenAI codex (`gpt-5.6-sol`, `--sandbox read-only`) + Cursor
agent (`--mode ask`), run in parallel.
**Rounds:** 1.
**Verdict:** both engines — **NO P1/P2 FINDINGS**. Three P3s raised
(converged across engines).

### Findings triaged

| # | Engine(s) | Sev | Finding | Verdict |
|---|-----------|-----|---------|---------|
| 1 | codex + cursor | P3 | `get_or_create` (api.py:68) ran **before** the type guards; sibling `create_block_from_event` runs it after — malformed payload created an empty `Schedule` row as a side effect | **ACCEPTED / fixed** — moved `get_or_create` below the type-guard block, mirroring the sibling. Pre-existing ordering (already true for the other early-return 400 paths) but aligned with the plan's "mirror sibling" intent. |
| 2 | codex + cursor | P3 | `assert resp.status_code != 500` (3 sites) is dead after the preceding `== 400` | **REJECTED / kept** — intentional documentation of issue #103's "400 (never 500)" acceptance criterion; harmless, communicates regression intent. |
| 3 | cursor | P3 | No test for non-string `end_time` (only `start_time` covered); loop is symmetric so code is correct, coverage gap only | **ACCEPTED / fixed** — added `test_non_string_end_time_returns_400`. |

### Fixes applied

- `backend/schedules/api.py` — moved `Schedule.objects.get_or_create(...)`
  to after the start/end/title/category type guards (F1).
- `backend/tests/test_views.py` — added
  `test_non_string_end_time_returns_400` (F3).

### Verification (post-fix)

- `uv run pytest backend/tests/test_views.py::TestCreateBlock -q` → **17
  passed**.
- `uv run ruff check backend/schedules/api.py backend/tests/test_views.py`
  → **All checks passed**.
- Note: repo-wide `ruff check backend/` reports 3 pre-existing
  import-order failures in unrelated AI test files — baseline noise, not
  from this patch (codex separated these explicitly).

**Result:** SUCCESS — zero valid P1/P2, tests + lint green.
