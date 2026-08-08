# Issue #119 — Code Review Trail

Fix: `block_detail` PATCH 500s on non-string `category`. Adds an
`isinstance(data["category"], str)` guard before the `VALID_CATEGORIES`
set-membership check, mirroring the `create_block` guard from issue #103.
Same bug class, different endpoint (deferred from PR #118).

## External review trail

**Engines:** OpenAI codex (`gpt-5.6-sol` — the codex CLI's configured
model id, passed verbatim as `codex exec -m gpt-5.6-sol`; not a typo) +
Cursor
agent (`--mode ask`), run in parallel against `git diff HEAD` in the
`feature/0119-block-detail-category-guard` worktree.
**Rounds:** 1.
**Verdict:** both engines — **NO P1/P2 FINDINGS**. codex: no P3. cursor:
2 P3s.

### Findings triaged

| # | Engine | Sev | Finding | Verdict |
|---|--------|-----|---------|---------|
| 1 | cursor | P3 | `docs/api.md` `category` error rows said only "Not one of the allowed choices"; after the guard, non-string category returns `"Category must be a string."` | **ACCEPTED / fixed** — updated the two *guarded* endpoints' `category` rows (`create_block` #103, `block_detail` this PR) to "Not a string, or not one of the allowed choices." The `restore_blocks` row was initially updated too but **reverted on PR #120 review**: that endpoint still lacks the guard (same 500 bug), so its doc must not claim a non-string 400 — tracked as issue #121. |
| 2 | cursor | P3 | Test name `test_non_string_category_returns_400_not_500` skips the local `test_patch_*` prefix used by adjacent `TestBlockDetail` tests | **REJECTED / kept** — deliberately mirrors the #103 `create_block` test name for cross-endpoint consistency, and matches issue #119's stated acceptance criterion verbatim. |

### Fixes applied

- `backend/schedules/api.py` — `isinstance` guard on `category` in
  `block_detail` (the core fix).
- `backend/tests/test_views.py` — `test_non_string_category_returns_400_not_500`
  in `TestBlockDetail` (TDD: written red first, confirmed `TypeError` 500,
  then green).
- `docs/api.md` — corrected the two guarded endpoints' `category`
  error-doc rows (`create_block`, `block_detail`); `restore_blocks` row
  left as-is pending issue #121 (P3 #1, refined on PR #120 review).
- `tasks/todo.md` — marked the 0042 (issue #103) follow-up done, linked issue #119.

### Verification (post-fix)

- `uv run pytest backend/tests/test_views.py::TestBlockDetail -q` → **16
  passed**.
- `uv run ruff check backend/schedules/api.py backend/tests/test_views.py`
  → **All checks passed**.

**Result:** SUCCESS — zero valid P1/P2, tests + lint green.
