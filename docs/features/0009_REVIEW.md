# 0009 Async AI Views — Code Review

## Findings

No actionable issues found in this pass.

The prior review findings are resolved:

- The `AsyncOpenAI` client is no longer a module-level singleton; `_get_client()` caches per running event loop and has regression coverage for same-loop reuse and different-loop separation.
- The AI view tests now pass under the current `.env` without forcing `DEBUG=1`; `backend/tests/conftest.py` disables HTTPS redirect/security-cookie behavior for tests.
- `backend/ai/service.py` now accurately documents the async client and the three public service entrypoints.

## Review Notes

The implementation matches the 0009 plan:

- `run_command`, `run_draft`, and `run_chat` are async and await `AsyncOpenAI`.
- Async cache APIs are used for rate limiting.
- Async ORM APIs are used for AI interaction logging.
- `request.auser()` is used in async views, including the command rate-limit wrapper.
- Transactional mutation blocks remain sync and are bridged with `sync_to_async(..., thread_sensitive=True)`.
- Service tests stay sync through `async_to_sync`, while view tests keep Django's sync `Client` and patch async service callables.

I did not find snake_case/camelCase mismatches, nested response-shape issues, or new over-engineering concerns. The extracted sync transaction helpers make the async boundary explicit and preserve rollback behavior.

## Verification

```bash
uv run ruff check backend/ai backend/tests/test_ai_service.py backend/tests/test_ai_service_draft.py backend/tests/test_ai_service_chat.py backend/tests/test_ai_views.py backend/tests/test_ai_views_draft.py backend/tests/test_ai_views_chat.py backend/tests/conftest.py
# All checks passed

uv run python backend/manage.py check
# 1 warning: schedules.W001 because this workspace has DEBUG=False + SQLite

uv run pytest backend/tests/test_ai_service.py backend/tests/test_ai_service_draft.py backend/tests/test_ai_service_chat.py backend/tests/test_ai_views.py backend/tests/test_ai_views_draft.py backend/tests/test_ai_views_chat.py -q
# 115 passed, 81 warnings

uv run pytest backend/tests/ -q
# 352 passed, 222 warnings
```
