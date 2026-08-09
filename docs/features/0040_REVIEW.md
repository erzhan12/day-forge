# Feature 0040 — Code Review Trail

Backend-test-only migration of the feature-0009 async-boundary regression
contract (the `_Rollback` re-raise across `await sync_to_async(_apply_actions_sync,
thread_sensitive=True)(...)` + atomic rollback) from the three orphan `/command/`
Playwright scripts into deterministic no-LLM pytest. No production code changed.
Plan: `docs/features/0040_PLAN.md` (passed plan-debate + ext-plan-review).

## External review trail

**Engines:** OpenAI codex (`gpt-5.6-sol`, `--sandbox read-only`) + Cursor agent
(`--mode ask`), run in parallel.
**Rounds:** 1.
**Change surface:** `backend/tests/test_ai_views.py`, `backend/tests/test_ai_views_chat.py`,
`tasks/todo.md`.

### Findings

Both engines returned **NO P1/P2 FINDINGS** and independently confirmed: all
three slices present + todo ticked; `test_rollback_propagates_across_sync_to_async`
genuinely drives the asgiref boundary (`async_to_sync(_run)()` → `await
sync_to_async(_apply_actions_sync, thread_sensitive=True)`), runs under standard
`@pytest.mark.django_db` (CurrentThreadExecutor reuses the pytest thread — no
connection-affinity error), and raises `_Rollback` with the 409 `schedule_changed`
response intact; the overlap-rollback asserts (`success is False`, `status ==
DRAFT`, `"overlap" in detail`, surviving-pk list) are all reachable; no
`async def test_` (which would silently no-op without pytest-asyncio); LLM fully
monkeypatched (no tokens). Both engines ran the suite → 88 passed.

Two P3 nits, both raised by both engines and both **ACCEPTED + FIXED**:

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | P3 | `test_ai_views.py:83` — `assert isinstance(excinfo.value, ai.views._Rollback)` redundant after `pytest.raises(ai.views._Rollback)`. | Removed the redundant assertion. |
| 2 | P3 | `test_ai_views_chat.py:603` — `isinstance(errors["action_index"], int)` is weaker than the command test (and accepts `bool`); the single-action scenario is deterministic. | Changed to `assert errors["action_index"] == 0` (symmetric with the command test). |

No findings rejected. No P1/P2 raised in either engine.

### Verification (after fixes)
- `uv run pytest backend/tests/test_ai_views.py backend/tests/test_ai_views_chat.py -q` → **88 passed**.
- `uv run ruff check backend/tests/...` → clean.
- Independent mutation check (main session): neutering the fingerprint-mismatch
  `raise _Rollback` makes `test_rollback_propagates_across_sync_to_async` FAIL —
  the load-bearing test is non-vacuous; `views.py` reverted clean.

### Result
Zero valid P1/P2; both P3s fixed. Tests + lint green. **SUCCESS.**
