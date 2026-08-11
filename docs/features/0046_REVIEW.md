# 0046 — Rules priority fix — Review trail

## External review trail (ext-code-review)

- **Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`agent`, ask mode)
- **Rounds:** 1
- **Scope:** `backend/templates_mgr/api.py`, `backend/tests/test_templates_api.py`,
  `frontend/src/components/RulesList.vue`, `frontend/tests/RulesList.test.ts`,
  `docs/api.md`, `RULES.md`, `docs/features/0046_PLAN.md`, `tasks/todo.md`

### Findings

| # | Sev | Verdict | Note |
|---|-----|---------|------|
| F1 | P2 | **REJECT** | `select_for_update()` no-op on SQLite. Pre-existing, cross-cutting, documented by `schedules.W001`; the lock already wrapped `rules_collection`/`rule_detail` before 0046. Not introduced by this change; dev-DB limitation. |
| F2 | P2→P3 | **DOWNGRADE / accepted gap** | Two-PATCH `bumpPriority` reorder is non-atomic; a concurrent create/delete can compact between the two PATCHes → transient stale value. Pre-existing non-atomicity (already tracked as `0026-followup: atomic reorder swap`). Worst case is a transient duplicate/stale priority that self-heals on the next reorder via the `-priority, id` tiebreak + the ±1 same-priority bias branch — no crash, no data loss. PATCH deliberately never compacts. Single-user, low-frequency. Non-blocking. |
| F3 | P3 | **ACCEPT / fixed** | Compaction tests had no second user → user-scoping unproven. Added `test_compaction_does_not_touch_other_users_rules`. |
| F4 | P3 | **ACCEPT / fixed** | Equal-priority `id`-tiebreak preservation uncovered. Added `test_compaction_preserves_id_tiebreak_for_equal_priorities`. |
| F5 | P3 | **REJECT** | Lock-order test "marginal" — existing create/delete compaction tests already exercise the locked path end-to-end. |
| cursor-P3 | P3 | **REJECT** | Cited `Edit.test.tsx` / `New.test.tsx` — files not in this repo. Hallucinated context. |

### Fixes applied this round

- Added two P3 regression tests (F3, F4) to `backend/tests/test_templates_api.py`.
- (Pre-review, during `/review-fix-loop-staged`) docstring clarity + `max+1` coupling
  comment in `api.py`; `docs/api.md` GET example corrected `priority: 10` → `0`;
  added `test_patch_does_not_compact_priorities`.

### Verification

- `uv run pytest backend/tests/test_templates_api.py -q` → **34 passed**
- `uv run ruff check backend/templates_mgr/ backend/tests/test_templates_api.py` → clean
- `npm test -- RulesList` → 11 passed (prior round)

**Result: SUCCESS — zero valid P1/P2, tests + lint green.**
