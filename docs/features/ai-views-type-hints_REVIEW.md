# ai/views.py type-hints — external review trail

Behaviour-neutral refactor: added parameter/return annotations to the ~22
internal helpers in `backend/ai/views.py` (branch `refactor/ai-views-type-hints`).
No type checker introduced — annotations are documentation/IDE-only.

## External review — iteration 1

- **Engines:** codex (`gpt-5.6-sol`, read-only) + cursor agent (`--mode ask`), parallel.
- **Scope:** `git diff main` — `backend/ai/views.py` + a `tasks/todo.md` tick.

| # | Sev | Finding | Verdict |
|---|-----|---------|---------|
| 1 | P2 (codex) / P3 (cursor) | `_validate_chat_messages(messages: list[dict])` is too narrow — it validates `data.get("messages")`, an **untrusted** value that can be `None`/non-list (that's the point of the validator). | **ACCEPTED, FIXED** → `messages: object` |
| 2 | P3 (both) | `_rate_limit_per_user(view_func: Callable)` — the wrapper always `await`s the view (async-only, documented), so a precise `Callable[..., Awaitable[JsonResponse]]` is better than bare `Callable`. | **ACCEPTED, FIXED** |
| 3 | P3 (cursor) | Public views `ai_command`/`ai_chat`/`ai_generate_draft` still lack `request`/`date` annotations. | **ACCEPTED gap, not fixed** — intentional scope boundary (task = internal helpers), consistent with bare Django views elsewhere (`schedules/api.py`). |

Both engines confirmed independently: the new imports (`Callable`, `Awaitable`,
`MutationDiff`, `AICommandResult`/`AIChatResult`/`AIDraftResult`) resolve with no
circular edge; eager annotation eval is runtime-neutral (no `from __future__`,
all names imported before use); the `AICommandResult | AIChatResult` union on
`_apply_actions_sync` and `AIDraftResult` on `_apply_draft_sync` match the call
sites; post-validation helpers (`_transcript_sha256`, `_build_chat_audit_response`,
`_log_chat_failure`) correctly keep `list[dict]`.

### Verification
- `uv run ruff check backend/` → clean.
- `uv run pytest backend/tests/test_ai_views.py backend/tests/test_ai_views_chat.py -q` → 86 passed.

### Result
Zero valid P1/P2 remaining (the one P2 fixed). Both P3s addressed (one applied,
one recorded as intentional scope). **SUCCESS.**
