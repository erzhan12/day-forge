---
name: 0009 — Async AI views (sync→async def conversion)
description: Convert all three AI endpoints from sync `def` to `async def` backed by `openai.AsyncOpenAI`, eliminating the structural barrier to serving concurrent AI requests without holding Django worker threads.
type: feature-plan
---

# 0009 — Async AI views (sync→async def conversion)

## Background

All three AI endpoints in `backend/ai/views.py` — `ai_command`, `ai_generate_draft`, `ai_chat` — are synchronous Django views. Each view calls the OpenAI-compatible LLM via the synchronous `openai.OpenAI` client in `backend/ai/service.py`. Under the default sync gunicorn worker model, every in-flight LLM request occupies one worker thread for the full duration of the call (up to `LLM_REQUEST_TIMEOUT`, default 15 s). Under concurrent AI load, N simultaneous requests consume all N workers and stall every other request site-wide, including manual schedule edits and page loads that have no LLM component.

This blocker is documented in `CLAUDE.md` § "Production Deployment" and is referenced in the 0008 plan's "Production-scale dependency" note. The `ai.E001` system check (`backend/ai/checks.py`) already enforces a shared-cache backend when `LLM_API_KEY` is set, which addresses the rate-limit bucket problem but not the worker starvation problem.

Converting the views to `async def` removes the structural barrier: async views yield the worker thread back to the event loop during the `await` on the LLM call. **Under a WSGI/sync gunicorn deployment (the current default), async views run in Django's thread pool executor — there is no concurrency win yet.** The win arrives in Phase 7 when the production runner is switched to uvicorn or gunicorn+uvicorn worker, **after** the middleware async-capability audit (D5) completes. This PR is deliberately preparatory: it clears the code-level barrier so Phase 7 is an infrastructure change (server class + middleware), not a code refactor under time pressure.

## Goal

Convert the three service-layer functions — `run_command`, `run_draft`, `run_chat` in `backend/ai/service.py` — and their view wrappers — `ai_command`, `ai_generate_draft`, `ai_chat` in `backend/ai/views.py` — from sync to `async def`. Replace the module-level `openai.OpenAI` singleton with `openai.AsyncOpenAI`. All helper functions that perform I/O (cache reads/writes, ORM reads/writes inside the views) are converted to use their async-native equivalents. Functional behaviour, wire format, error taxonomy, and all existing test assertions remain unchanged.

## Out of scope

- Redis / shared-cache migration (separate upcoming PR; `ai.E001` continues to block `DEBUG=False` deploys).
- Celery / background-task path (heavier alternative, not pursued).
- ASGI server runner switch (deferred to Phase 7 deploy work; see `PHASES.md`).
- Changes to `backend/ai/prompts.py` or `backend/ai/schemas.py` (pure functions, no I/O).
- Any frontend changes.

---

## Decisions table

### D0 — Authenticated user resolution in async views

Every current view uses `request.user` (22 sites in `views.py`: lines 122, 440, 503, 524, 567, 585, 604, 615, 630, ...). Under WSGI, `request.user` is a `SimpleLazyObject` that lazily resolves via a **sync** DB query when first accessed. Inside an `async def` view, that lazy resolution triggers `SynchronousOnlyOperation` — Django explicitly forbids implicit sync ORM from async context. The `@login_required` decorator has a separate async branch that resolves `request.auser()` but **does not populate `request.user`** — the lazy proxy still points at the sync resolver.

**Scope of resolution — view body AND the `_rate_limit_per_user` decorator wrapper:** the rate-limit wrapper at [views.py:120](backend/ai/views.py#L120) runs **before** the view body and itself reads `request.user.id`. After the async port, the wrapper is `async def wrapper(request, ...)` and must resolve the user via `await request.auser()` itself — it cannot rely on the view body to do so, since the wrapper executes first. Otherwise the command endpoint raises `SynchronousOnlyOperation` before it ever enters `ai_command`.

**Decision:** Resolve once per call, at the earliest async frame that needs `request.user.id`:

```python
# Decorator wrapper (runs BEFORE the view body)
@functools.wraps(view_func)
async def wrapper(request, *args, **kwargs):
    user = await request.auser()
    if not await _consume_rate_limit(
        user.id, "ai_cmd_rl", settings.LLM_RATE_LIMIT_PER_HOUR
    ):
        return _rate_limited_response()
    return await view_func(request, *args, **kwargs)

# View body
@login_required
async def ai_command(request, date):
    user = await request.auser()
    # ... use `user` / `user.id` instead of `request.user` / `request.user.id`
```

The double `await request.auser()` (once in the decorator wrapper, once in the view body) is cheap — Django caches the resolved user on `request._acached_user` after the first call (see [django/contrib/auth/middleware.py:24-27](.venv/lib/python3.14/site-packages/django/contrib/auth/middleware.py#L24-L27); the sync `request.user` path uses a separate `_cached_user` attribute), so the second resolution is an `hasattr` short-circuit, not a DB query.

The `@login_required` decorator itself works on async views (Django 4.1+ — see `django.contrib.auth.decorators.login_required` source: it has an `iscoroutinefunction(view_func)` branch). No decorator rewrite needed for `@login_required`; only the project-local `_rate_limit_per_user` wrapper requires the auser() call.

**Alternative considered:** Resolve in the wrapper and pass `user` as an injected kwarg to the view body. Rejected: changes the view signature, ripples through tests and URL kwargs. The double-resolve-with-cache pattern is cheaper to ship.

### D1 — Rate-limit cache reads/writes

`_consume_rate_limit` in `views.py` calls `cache.add`, `cache.incr`, and `cache.set`.

**Decision:** Use Django's native async cache API — `cache.aadd`, `cache.aincr`, `cache.aset` — available since Django 4.1. The project targets Django 5.x (see `pyproject.toml`), so these are stable. Convert `_consume_rate_limit` to `async def _consume_rate_limit(...)` and `await` each call. All three call sites (`ai_command` decorator wrapper, `ai_generate_draft` inline, `ai_chat` inline) are already inside async views by the time D1 applies.

**Alternative considered:** Wrap the entire function body in `sync_to_async(_consume_rate_limit)`. Rejected: the async cache API is purpose-built and avoids the thread-pool round-trip; `sync_to_async` is the right escape hatch when no async alternative exists, not here.

**Impact on `_rate_limit_per_user` decorator:** The decorator wraps a sync view today. With `ai_command` converted to `async def`, the decorator must also be `async def`-aware. Convert the `wrapper` inner function to `async def wrapper(...)` and `await _consume_rate_limit(...)` and `await view_func(...)`. The `@functools.wraps` annotation is unchanged.

### D2 — AIInteraction DB writes

`_log_interaction` calls `AIInteraction.objects.create(...)` (ORM write). `_mark_success` calls `interaction.save(update_fields=["success"])`.

**Decision:** Convert both helpers to `async def` using the async ORM: `await AIInteraction.objects.acreate(...)` in `_log_interaction` and `await interaction.asave(update_fields=["success"])` in `_mark_success`. Django 4.1+ provides `acreate` / `asave` on all model managers. The try/except-swallow pattern in both helpers is preserved verbatim — a logging failure must never propagate to the caller.

**Alternative considered:** `sync_to_async(_log_interaction)`. Rejected for the same reason as D1: async ORM is available and is the idiomatic choice.

### D3 — Schedule / TimeBlock mutations inside `transaction.atomic()`

`_apply_actions`-family functions (`_apply_add`, `_apply_move_or_resize`, `_apply_remove`, `_apply_existing_block_action`, `_apply_action`) perform sync ORM writes (`block.save()`, `block.delete()`, `block.full_clean()`). The view wraps these in `transaction.atomic()` and uses the `_Rollback(JsonResponse)` exception-as-control-flow pattern to abort the transaction *and* return a response from the caught exception's `.response` attribute (see [backend/ai/views.py:189](backend/ai/views.py#L189) for the class, lines 499-500, 680, 697-698, 960-961 for the raise sites, and lines 500, 698, 961 for the `except` handlers).

**Decision:** Keep `_apply_*` helpers and the outer `with transaction.atomic(): …` block **sync**. Wrap the whole atomic block in `sync_to_async(..., thread_sensitive=True)` inside the async view. Preserve the `_Rollback` exception verbatim — re-raise from inside the sync helper, catch outside `await`. `asgiref.sync.SyncToAsync` re-raises exceptions across the thread boundary, so the existing pattern works unchanged.

```python
def _apply_command_sync(schedule, result) -> None:
    # body verbatim from current ai_command:
    with transaction.atomic():
        locked_blocks = list(TimeBlock.objects.filter(schedule=schedule).select_for_update())
        blocks_by_id = {b.id: b for b in locked_blocks}
        for idx, action in enumerate(result.parsed_actions):
            err = _apply_action(schedule, blocks_by_id, action, idx)
            if err is not None:
                raise _Rollback(err)   # ← unchanged. atomic() rolls back on exception.

# in async view:
try:
    await sync_to_async(_apply_command_sync, thread_sensitive=True)(schedule, result)
except _Rollback as rb:
    return rb.response
```

**Why NOT `return JsonResponse` from inside `transaction.atomic()`:** a normal `return` from inside an atomic block is treated as **successful exit** by `transaction.atomic.__exit__` — partial writes from earlier loop iterations get **committed**. The only way to roll back without crashing the caller is `raise SomeException` (Django catches anything that isn't `DatabaseError` and re-raises after rollback) or explicit `transaction.set_rollback(True)` before return. The existing `_Rollback` mechanism is the right pattern and must survive the async port unchanged.

**Why NOT `transaction.aatomic()`:** verified against installed Django 5.2.12 — **`transaction.aatomic` does not exist**. There is no async context manager for transactions in this Django version. `sync_to_async` is the only option, not the safest-among-options. `select_for_update` under SQLite is silently ignored (see `schedules.W001`) but the `_Rollback` semantics are required regardless of backend, so the sync wrapper is correct for PostgreSQL too.

**`thread_sensitive=True`:** ensures the wrapped sync block runs on the dedicated DB-state thread that asgiref reserves for sync operations, so connection pooling and any in-flight transaction state for the same request are coherent. `False` would dispatch onto a fresh worker thread with a separate DB connection — wrong for transactional code.

### D4 — Tests

**Existing mock pattern:** All three service test files (`test_ai_service.py`, `test_ai_service_draft.py`, `test_ai_service_chat.py`) define a local `FakeCompletions` class whose `create` method is a plain synchronous `def`. After converting the service to `AsyncOpenAI`, the SDK's `client.chat.completions.create(...)` becomes a coroutine — `await` in service code will fail if the mock returns a plain value.

**Decision (service-layer mocks):** Replace the `FakeCompletions.create` sync method with `async def create(self, **kwargs)` in all three service test files.

**Decision (service-layer test bodies — keep sync, invoke via `async_to_sync`):** Verified against the existing tests — `test_ai_service_draft.py` does sync ORM setup directly in test bodies (10 sites: `Schedule.objects.create(...)`, `Template.objects.create(...)`, see [test_ai_service_draft.py:55-60](backend/tests/test_ai_service_draft.py#L55-L60)). Converting these tests to `async def test_...` would require replacing every `.objects.create(...)` with `await ....objects.acreate(...)`, `.refresh_from_db()` with `await ....arefresh_from_db()`, and so on — a substantial rewrite that the original plan claimed wouldn't happen.

**Avoided by:** keep service tests as sync `def test_...`. Invoke the now-async service via `asgiref.sync.async_to_sync`:

```python
from asgiref.sync import async_to_sync
# ...

def test_run_draft_xxx(user, monkeypatch, settings):
    schedule = Schedule.objects.create(user=user, date=...)   # sync — unchanged
    template = Template.objects.create(...)                    # sync — unchanged
    result = async_to_sync(run_draft)(schedule, template, [], [], now)   # awaitable wrapped — full signature: (schedule, template, history_schedules, rules, now)
    assert result.parsed_actions == [...]                      # sync — unchanged
```

`test_ai_service.py` and `test_ai_service_chat.py` have **zero sync ORM in test bodies** (verified via grep) — they only use a fixture `user` and fake clients. Same `async_to_sync(run_command)(...)` / `async_to_sync(run_chat)(...)` pattern applies. The fake `FakeCompletions.create` still needs `async def` so the awaited call inside the service resolves — that's independent of the test body's sync/async-ness.

**Consequence: pytest-asyncio is NOT needed.** Service tests stay sync, view tests stay sync. Drop the `pytest-asyncio>=0.23` dep + `asyncio_mode = "auto"` settings.

**View-layer test client — keep sync `Client`, NOT `AsyncClient`:** Verified against installed Django 5.2.12 — `AsyncClient.post` is `async def` ([client.py:1495](.venv/lib/python3.14/site-packages/django/test/client.py#L1495)). Using it forces every view test body to become `async def` with `await client.post(...)`, and every subsequent ORM assertion becomes `SynchronousOnlyOperation` inside the async test body. Django's sync `Client` works with async views out of the box — it adapts via `async_to_sync` internally. View tests stay sync `def`, `client.post(...)` stays sync, ORM assertions stay sync. The only change in view tests is the monkeypatch payload: `_patch_run` installs an `async def _run(...)` (or `unittest.mock.AsyncMock`) because the view now `await`s the service call.

**Test for the rate-limit `incr`-after-evict path:** [test_ai_views.py:614-635](backend/tests/test_ai_views.py#L614-L635) (`test_cache_incr_value_error_reseeds_counter`) monkeypatches `ai.views.cache.incr` to raise `ValueError`. After D1 the production code calls `cache.aincr`, so this test must monkeypatch `ai.views.cache.aincr` instead — and the replacement must be `async def` (or `AsyncMock`) since the call site is now awaited. Listed explicitly in the mock-changes table below.

**Note:** `asgiref` is already a transitive dependency of Django 4.1+ (used by `sync_to_async` and `async_to_sync`). No explicit `pyproject.toml` entry needed. **No new dev dependency required.**

### D5 — ASGI server runner

**Decision:** Deferred to Phase 7 (`PHASES.md` Phase 7 deploy work).

- **Local dev:** `manage.py runserver` already auto-detects async views and runs them on Django's built-in async-capable dev server. No change needed.
- **Production (current):** gunicorn sync workers. Async views run in Django's `SyncToAsync` thread pool executor — each request still consumes a thread for the duration of the LLM call. **No concurrency win yet** — this PR removes the code-level barrier only.
- **Production (Phase 7):** Switch to `uvicorn` or `gunicorn --worker-class uvicorn.workers.UvicornWorker`. A single worker process can then handle N concurrent async views with no thread starvation. **However, Phase 7 is NOT a one-line config change — see middleware audit below.**

**Middleware async-capability audit (Phase 7 prerequisite, NOT this PR):**

The project's `MIDDLEWARE` setting ([backend/day_forge/settings.py:39-49](backend/day_forge/settings.py#L39-L49)) includes third-party components that may be sync-only:
- `whitenoise.middleware.WhiteNoiseMiddleware` (line 41) — sync-only as of WhiteNoise 6.x; Django adapts it via per-request `sync_to_async` bridge.
- `inertia.middleware.InertiaMiddleware` (line 43) — sync-only; same bridge.
- All `django.*` middleware in current Django versions advertise `async_capable = True` (verified on Django 5.2.12).

Under an ASGI runner, Django wraps each sync-only middleware in a `sync_to_async` call **per request**. Even with async views, every request still pays a thread-bridge cost on the way in and out of the middleware stack. The result: the worker-starvation problem is mitigated for the **LLM-wait window** (a thread is freed during the OpenAI HTTP call) but the per-request middleware bridge can still cap concurrency below the theoretical async maximum.

**Phase 7 follow-up must include:**
1. Audit `async_capable` attribute on every entry in `MIDDLEWARE`.
2. For sync-only third-party middleware (WhiteNoise, Inertia, others): upgrade to async-capable versions if available, replace with async equivalents (e.g. serve static via a dedicated CDN/nginx instead of WhiteNoise), or accept the per-request bridge cost as a tradeoff.
3. Benchmark concurrent AI request throughput before vs after the ASGI switch to confirm the bridge cost doesn't dominate.

Reviewers reading this PR should understand the concurrency benefit is **not** delivered by this PR alone, and Phase 7 is **not** a one-line server-class flip — it depends on the middleware audit completing first.

### D6 — Timeout handling

`openai.AsyncOpenAI` mirrors `openai.OpenAI` for timeout configuration: both accept `timeout=` at the constructor and as a per-call override on `chat.completions.create(...)`. Under the hood, `AsyncOpenAI` uses `httpx.AsyncClient`; `OpenAI` uses `httpx.Client`. Both map `timeout=` to the same `httpx.Timeout` semantics.

**Existing pattern in `service.py`:** the current code passes `timeout=settings.LLM_REQUEST_TIMEOUT` per-call on `chat.completions.create(...)`, not at the constructor. **Keep that pattern unchanged** after the port — `await client.chat.completions.create(..., timeout=settings.LLM_REQUEST_TIMEOUT)`. No constructor change needed.

**Timeout exception:** `openai.APITimeoutError` is raised in both sync and async paths — the SDK wraps the underlying `httpx.TimeoutException` in `openai.APITimeoutError` regardless of client type. The existing `except openai.APITimeoutError` catch in `run_command`, `run_draft`, and `run_chat` requires no changes.

**Verification:** Confirm at implementation time against the installed `openai>=2.8.1` SDK (pinned in `pyproject.toml`). The async client and per-call `timeout=` have been stable since `openai>=1.0`.

### D7 — PR staging strategy (revised — honest)

The original phased plan (PR-per-endpoint) is **not viable without a dual-client shim** because `_get_client()` is a module-level singleton returning the same client object to all three `run_*` functions. Converting it to `AsyncOpenAI` in PR #1 forces all three service functions to be `async def` in the same PR, which in turn forces all three view wrappers to be `async def` (you can't `await run_draft(...)` from a sync view without `async_to_sync`, and `async_to_sync` inside a sync view from inside a request handler is an event-loop-mismatch footgun).

Two honest options:

**Option A — Monolithic PR (recommended):** One PR converts the whole vertical slice in one commit train:
- service layer (all three `run_*` + `_get_client` → `AsyncOpenAI`)
- views (`ai_command`, `ai_generate_draft`, `ai_chat` + helpers `_consume_rate_limit`, `_log_interaction`, `_log_chat_failure`, `_mark_success`, `_rate_limit_per_user`)
- mutation blocks → `sync_to_async(_apply_*_sync, thread_sensitive=True)` (preserving `_Rollback`)
- all six AI test files (service mocks `async def create`; view tests stay sync `Client`, only `_patch_run` payloads become `async def`)
- `pyproject.toml` — **no changes required** (service & view tests stay sync, invoking the async service via `async_to_sync`; see D4)

**Rationale for Option A:** the diff is large (~400 lines of view/service changes + ~300 lines of test changes), but every change is mechanical and isolated to the AI subsystem. Reviewer load is concentrated, not split across three half-converted states. Rollback is one revert.

**Option B — Two PRs with a sync+async client shim:** PR #1 introduces `_get_sync_client()` (returns `openai.OpenAI`) + `_get_async_client()` (returns `openai.AsyncOpenAI`) side-by-side. The first endpoint (`ai_command`) switches to `_get_async_client()` + `async def`. `run_draft` and `run_chat` keep calling `_get_sync_client()`. PR #2 finishes the migration and deletes the sync client. Manageable but adds throwaway code and a transient inconsistency.

**Decision:** Option A. The shim in Option B has zero production lifetime (a few days) but adds review surface for code that will be deleted. Two PRs that each touch the test infrastructure (Option B touches it twice) is worse than one PR that touches it once. The previous phased plan was incorrect.

| PR | Scope | Gate to merge |
|----|-------|---------------|
| Single PR | Service layer (all three `run_*` → `async def`, client → `AsyncOpenAI`) + views (all three → `async def`, `_apply_*_sync` extraction, helpers async) + tests (service `FakeCompletions.create` → `async def`; test bodies stay sync, invoke service via `async_to_sync`; view tests stay sync with async monkeypatches) | All 6 AI test files green; `uv run python backend/manage.py check` green; manual smoke of all three endpoints in dev; all 6 Playwright chat scripts pass |

Smaller follow-up PRs (sequenced after the monolithic PR merges) can address: (a) middleware async-capability audit (D5 prerequisite for Phase 7), (b) Redis cache migration (separate concern, blocks `DEBUG=False` deploy), (c) Phase 7 ASGI runner switch.

---

## Implementation — single PR

**Files changed (complete list):**

- `backend/ai/service.py`
  - `from openai import OpenAI` → `from openai import AsyncOpenAI`.
  - `_client: OpenAI | None` → `_client: AsyncOpenAI | None`.
  - `_get_client()` returns `AsyncOpenAI` (sync factory — constructor makes no I/O call).
  - `run_command`, `run_draft`, `run_chat` → `async def`. Each has exactly one `await` on `client.chat.completions.create(...)`.
- `backend/ai/views.py`
  - `_consume_rate_limit` → `async def` (uses `cache.aadd` / `cache.aincr` / `cache.aset`).
  - `_log_interaction` → `async def` (uses `AIInteraction.objects.acreate`).
  - `_log_chat_failure` → `async def` (calls `await _log_interaction(...)`). **Must be converted — currently sync, called from chat error path at line 904.**
  - `_mark_success` → `async def` (uses `interaction.asave(...)`).
  - `_rate_limit_per_user` decorator's inner `wrapper` → `async def wrapper(...)`.
  - `ai_command`, `ai_generate_draft`, `ai_chat` → `async def`.
  - Each view starts with `user = await request.auser()` and uses `user` / `user.id` thereafter (D0).
  - Extract `_apply_command_sync`, `_apply_draft_sync`, `_apply_chat_sync` from the three views — each is the `with transaction.atomic(): …` block lifted verbatim, raising `_Rollback` on action errors as the existing code does.
  - Views call `await sync_to_async(_apply_*_sync, thread_sensitive=True)(schedule, result)` and keep the `except _Rollback as rb: return rb.response` handler.
  - `_Rollback` class definition unchanged.
- `backend/tests/test_ai_service.py` — `FakeCompletions.create` → `async def`.
- `backend/tests/test_ai_service_draft.py` — `_FakeChat.create` → `async def`.
- `backend/tests/test_ai_service_chat.py` — `FakeCompletions.create` → `async def`.
- `backend/tests/test_ai_views.py` — `_patch_run` installs `async def _run(...)`; `test_cache_incr_value_error_reseeds_counter` ([line 614](backend/tests/test_ai_views.py#L614)) repointed to `ai.views.cache.aincr` with an `async def` raiser.
- `backend/tests/test_ai_views_draft.py` — equivalent patch helper updated to `async def`.
- `backend/tests/test_ai_views_chat.py` — equivalent patch helper updated to `async def`.
- `pyproject.toml` — **no changes**. Service & view tests stay sync; `async_to_sync` (from `asgiref`, already a transitive dep) wraps the awaitable service entrypoints inside sync test bodies. No `pytest-asyncio` needed.

**Specific function-level changes in `views.py`:**

```
_consume_rate_limit(user_id, key_prefix, limit) → async def
  cache.add  → await cache.aadd
  cache.incr → await cache.aincr   ← (with except ValueError → await cache.aset fallback)
  cache.set  → await cache.aset

_log_interaction(schedule, command, response_text, actions, kind) → async def
  AIInteraction.objects.create(...)  → await AIInteraction.objects.acreate(...)

_log_chat_failure(schedule, last_user_msg, messages, exc) → async def
  _log_interaction(...)  → await _log_interaction(...)
  (call site at line 904 in ai_chat becomes `await _log_chat_failure(...)`)

_mark_success(interaction) → async def
  interaction.save(update_fields=...)  → await interaction.asave(update_fields=...)

_rate_limit_per_user decorator wrapper
  def wrapper(request, *args, **kwargs)  → async def wrapper(request, *args, **kwargs)
  request.user.id                        → user = await request.auser(); user.id   ← D0, MUST be inside wrapper
  _consume_rate_limit(user.id, ...)      → await _consume_rate_limit(user.id, ...)
  view_func(request, *args, **kwargs)    → await view_func(request, *args, **kwargs)

ai_command(request, date) → async def
  user = await request.auser()                                         ← D0
  Schedule.objects.get_or_create(user=user, ...)
    → await Schedule.objects.aget_or_create(user=user, ...)
  TimeBlock.objects.filter(...).order_by(...) (snapshot)
    → [b async for b in TimeBlock.objects.filter(...).order_by(...)]   ← .alist() does NOT exist in Django 5.2.12
  run_command(...)  → await run_command(...)
  _log_interaction(...)  → await _log_interaction(...)
  with transaction.atomic(): … raise _Rollback(err) …
    → await sync_to_async(_apply_command_sync, thread_sensitive=True)(schedule, result)
       (raise _Rollback inside helper, catch outside the await — atomic() rolls back on exception)
  _mark_success(...)  → await _mark_success(...)
  schedule.mark_active_on_edit()
    → await sync_to_async(schedule.mark_active_on_edit, thread_sensitive=True)()
  TimeBlock.objects.filter(...) (final response payload)
    → [b async for b in TimeBlock.objects.filter(...).order_by(...)]

ai_generate_draft(request, date) → async def
  user = await request.auser()                                         ← D0
  Schedule.objects.get_or_create(user=user, ...)
    → await Schedule.objects.aget_or_create(user=user, ...)
  TimeBlock.objects.filter(schedule=schedule).exists()
    → await TimeBlock.objects.filter(schedule=schedule).aexists()
  Template.objects.filter(user=user, type=...).first()
    → await Template.objects.filter(user=user, type=...).afirst()
  Schedule.objects.filter(...).select_related(...).prefetch_related(...) history
    → [s async for s in Schedule.objects.filter(...).select_related("daily_review").prefetch_related("time_blocks").order_by(...)]
       (async for evaluates select_related and prefetch_related in one round trip,
        same as the current sync materialisation; N+1 fix from PR #15 preserved.)
  Rule.objects.filter(user=user, is_active=True).order_by(...)
    → [r async for r in Rule.objects.filter(user=user, is_active=True).order_by(...)]
  run_draft(...)  → await run_draft(...)
  _log_interaction(...)  → await _log_interaction(...)
  with transaction.atomic(): … raise _Rollback(...) …
    → await sync_to_async(_apply_draft_sync, thread_sensitive=True)(schedule, result)
       (the pre-existing locked-blocks-non-empty 409 path also raises _Rollback;
        keep that semantics inside the sync helper)
  _mark_success(...)  → await _mark_success(...)
  TimeBlock.objects.filter(...) (final response payload)
    → [b async for b in TimeBlock.objects.filter(...).order_by(...)]

ai_chat(request, date) → async def
  user = await request.auser()                                         ← D0
  Schedule.objects.get_or_create(user=user, ...)
    → await Schedule.objects.aget_or_create(user=user, ...)
  TimeBlock.objects.filter(schedule=schedule).order_by(...) (snapshot)
    → [b async for b in TimeBlock.objects.filter(...).order_by(...)]
  run_chat(...)  → await run_chat(...)
  _log_chat_failure(...)  → await _log_chat_failure(...)
  _log_interaction(...)  → await _log_interaction(...)
  with transaction.atomic(): … raise _Rollback(...) …
    → await sync_to_async(_apply_chat_sync, thread_sensitive=True)(schedule, result)
  _mark_success(...)  → await _mark_success(...)
  schedule.mark_active_on_edit()
    → await sync_to_async(schedule.mark_active_on_edit, thread_sensitive=True)()
  TimeBlock.objects.filter(...) (final response payload)
    → [b async for b in TimeBlock.objects.filter(...).order_by(...)]
```

**Note on async iteration syntax:** Django 5.2.12's `QuerySet` exposes `__aiter__` (line 389 in `query.py`) and `aiterator()` (line 531), but **does not** expose a `.alist()` method. The pattern `[x async for x in queryset]` is the supported way to materialise a queryset asynchronously. Alternative: `await sync_to_async(list)(queryset)` — equivalent for short result sets, marginally heavier for long ones.

**Sync-wrapper helper design (D3) — KEEP `_Rollback`:**

Extract three private sync helpers from the existing `with transaction.atomic():` blocks. Each helper preserves the existing `_Rollback(JsonResponse)` exception-as-control-flow verbatim. `asgiref.sync.SyncToAsync` re-raises exceptions across the thread boundary, so `_Rollback` propagates back to the async caller cleanly.

```python
def _apply_command_sync(schedule, result) -> None:
    """Lifted verbatim from ai_command. Raises _Rollback(JsonResponse) to abort+respond."""
    with transaction.atomic():
        locked_blocks = list(
            TimeBlock.objects.filter(schedule=schedule).select_for_update()
        )
        blocks_by_id = {b.id: b for b in locked_blocks}
        for idx, action in enumerate(result.parsed_actions):
            err = _apply_action(schedule, blocks_by_id, action, idx)
            if err is not None:
                raise _Rollback(err)   # ← unchanged. atomic() rolls back on exception.

def _apply_draft_sync(schedule, result) -> None:
    """Lifted verbatim from ai_generate_draft."""
    with transaction.atomic():
        Schedule.objects.select_for_update().get(pk=schedule.pk)
        locked_blocks = list(TimeBlock.objects.filter(schedule=schedule))
        if locked_blocks:
            raise _Rollback(
                JsonResponse(
                    {"errors": {"detail": "Schedule is no longer empty; refusing to overwrite."}},
                    status=409,
                )
            )
        blocks_by_id: dict = {}
        for idx, action in enumerate(result.parsed_actions):
            err = _apply_add(schedule, blocks_by_id, action, idx)
            if err is not None:
                raise _Rollback(err)

def _apply_chat_sync(schedule, result) -> None:
    """Lifted verbatim from ai_chat."""
    with transaction.atomic():
        locked_blocks = list(
            TimeBlock.objects.filter(schedule=schedule).select_for_update()
        )
        blocks_by_id = {b.id: b for b in locked_blocks}
        for idx, action in enumerate(result.parsed_actions):
            err = _apply_action(schedule, blocks_by_id, action, idx)
            if err is not None:
                raise _Rollback(err)
```

Each async view's call site:

```python
try:
    await sync_to_async(_apply_command_sync, thread_sensitive=True)(schedule, result)
except _Rollback as rb:
    return rb.response
```

**Why NOT return-value pattern (rejected):** `return JsonResponse(...)` from inside `transaction.atomic()` exits the context manager via the normal-return path, which commits the transaction. Partial action writes from earlier loop iterations would be persisted. `_Rollback` (exception) is the only way to abort + return — Django catches any non-`DatabaseError` exception in `transaction.atomic.__exit__`, rolls back, and re-raises. Keep the existing semantics.

---

## Test plan

### Unit tests (mocked LLM)

**Service layer** — `backend/tests/test_ai_service.py`, `test_ai_service_draft.py`, `test_ai_service_chat.py`:
- Each file's `FakeCompletions.create` / `_FakeChat.create` becomes `async def`. All existing test cases are preserved verbatim; only the mock machinery changes.
- Service-layer tests **stay sync `def test_...`**. They invoke the now-async service via `async_to_sync(run_command)(...)` / `async_to_sync(run_draft)(...)` / `async_to_sync(run_chat)(...)`. This preserves the existing sync ORM setup in test bodies (notably the 10 sync ORM sites in `test_ai_service_draft.py`). No `pytest-asyncio` dependency.

**View layer** — `backend/tests/test_ai_views.py`, `test_ai_views_draft.py`, `test_ai_views_chat.py`:
- **Keep the sync `Client` (NOT `AsyncClient`).** Django's sync `Client` auto-adapts async views via `async_to_sync` internally — view test bodies, fixtures (`auth_client`, `conftest.py`), and ORM assertions stay **unchanged**.
- The only change in view tests: each `_patch_run` helper installs `async def _run(*args, **kwargs): ...` because `run_command` / `run_draft` / `run_chat` are now `async def` and the views `await` them. `unittest.mock.AsyncMock` is an equivalent alternative.
- `@pytest.mark.django_db` works as today.

**Specific tests requiring mock adjustment (complete list):**

| File | Test class / function | Change |
|------|----------------------|--------|
| `test_ai_service.py` | All tests using `patch_client` fixture | `FakeCompletions.create` → `async def`; test bodies stay sync; service call wrapped: `async_to_sync(run_command)(...)` |
| `test_ai_service_draft.py` | All tests using `_FakeClient` | `_FakeChat.create` → `async def`; test bodies stay sync (preserves 10 sync ORM setup sites); service call wrapped: `async_to_sync(run_draft)(...)` |
| `test_ai_service_chat.py` | All tests using `patch_client` fixture, `TestUntrustedTranscript` | `FakeCompletions.create` → `async def`; test bodies stay sync; service call wrapped: `async_to_sync(run_chat)(...)` |
| `test_ai_views.py` | All tests using `_patch_run` | `_patch_run` installs `async def _run`; test bodies remain sync |
| `test_ai_views.py` | `test_cache_incr_value_error_reseeds_counter` (line 614) | repoint `monkeypatch.setattr` from `ai.views.cache.incr` to `ai.views.cache.aincr`; replacement is `async def _raise_value_error(...)` |
| `test_ai_views_draft.py` | All tests with `run_draft` monkeypatch | replacement → `async def`; test bodies remain sync |
| `test_ai_views_chat.py` | All tests with `run_chat` monkeypatch | replacement → `async def`; test bodies remain sync |

**Verification grep (run after edits, then read the hits — do not expect empty output):**

```bash
grep -rn "def create\|def _run\|monkeypatch.setattr.*run_command\|monkeypatch.setattr.*run_draft\|monkeypatch.setattr.*run_chat\|cache\.incr\|cache\.add\|cache\.set" backend/tests/test_ai_*.py
```

The pattern is intentionally broad: it matches both `def create` and `async def create`, and may hit comments or docstrings. Implementation should inspect each match and confirm: (1) any non-`async def create` / non-`async def _run` over a now-awaited call site is updated, (2) `cache.incr` / `cache.add` / `cache.set` references in production-code monkeypatches are repointed to `aincr` / `aadd` / `aset`. An empty result is **not** the success condition — accurate matches are.

### Integration tests (Django test client)

Sync `client.post` / `auth_client.post` continue to work against async views (Django adapts internally). No structural change to test bodies. No `AsyncClient` migration needed. No `conftest.py` change needed.

### Manual e2e (Playwright scripts)

Wire format is **unchanged** — all 6 existing scripts validate correctly after the async conversion:

| Script | Endpoint validated |
|--------|--------------------|
| `frontend/scripts/playwright/ai-chat-single-turn-apply.mjs` | `ai_chat` |
| `frontend/scripts/playwright/ai-chat-clarifying-question.mjs` | `ai_chat` |
| `frontend/scripts/playwright/ai-chat-clear-cancels-inflight.mjs` | `ai_chat` |
| `frontend/scripts/playwright/ai-chat-date-change-resets-thread.mjs` | `ai_chat` |
| `frontend/scripts/playwright/ai-chat-privacy-hint-always-on.mjs` | `ai_chat` |
| `frontend/scripts/playwright/ai-chat-token-race.mjs` | `ai_chat` |

No `ai_command` or `ai_generate_draft` Playwright scripts exist in the current codebase. Manual browser smoke testing covers those two endpoints.

---

## Verification commands

Run after the single-PR changes are applied:

```bash
# Install / sync deps (no new entries this PR; asgiref already present via Django)
uv sync

# Lint
uv run ruff check backend/

# System checks (ai.E001 still blocks if LLM_API_KEY set + LocMem — out of scope for this PR)
uv run python backend/manage.py check

# Full test suite
uv run pytest backend/tests/ -v

# Targeted by subsystem (useful during iteration)
uv run pytest backend/tests/test_ai_service.py backend/tests/test_ai_service_draft.py backend/tests/test_ai_service_chat.py -v
uv run pytest backend/tests/test_ai_views.py backend/tests/test_ai_views_draft.py backend/tests/test_ai_views_chat.py -v

# Verification grep — inspect every match; flag SYNC `def create` / `def _run`
# over awaited call sites. NOTE: this matches `async def create` too, and may
# match comments / docstrings — read the hits, don't expect an empty result.
grep -rn "def create\|def _run\|cache\.incr\|cache\.add\|cache\.set" backend/tests/test_ai_*.py

# Manual dev server smoke (both terminals)
uv run python backend/manage.py runserver 8006
cd frontend && npm run dev
# Then exercise /command/, /generate-draft/, /chat/ via the UI
```

Manual e2e gate — all six Playwright chat scripts pass (requires `LLM_API_KEY` configured):

```bash
node frontend/scripts/playwright/ai-chat-single-turn-apply.mjs
node frontend/scripts/playwright/ai-chat-clarifying-question.mjs
node frontend/scripts/playwright/ai-chat-clear-cancels-inflight.mjs
node frontend/scripts/playwright/ai-chat-date-change-resets-thread.mjs
node frontend/scripts/playwright/ai-chat-privacy-hint-always-on.mjs
node frontend/scripts/playwright/ai-chat-token-race.mjs
```

---

## Risks / unknowns

**WSGI-thread-pool caveat (no concurrency win until Phase 7).** Under the current gunicorn sync worker deployment, `async def` views are run via `asgiref.sync.SyncToAsync` thread pool — each still occupies a thread. The structural barrier is removed; the operational win requires Phase 7's ASGI runner switch + middleware audit (D5). This must be stated explicitly in the PR description to set reviewer expectations.

**`transaction.aatomic` does not exist in Django 5.2.12.** Verified at plan time. The only async-safe way to run a transaction from an async view is to lift the `with transaction.atomic():` block into a sync helper and call it via `sync_to_async(..., thread_sensitive=True)` (D3). If Django adds an async transaction context manager in a future release, the helpers can be inlined — but for now the wrapper pattern is required, not preferred.

**Middleware async-capability under Phase 7.** `WhiteNoiseMiddleware` and `InertiaMiddleware` are sync-only. Under an ASGI runner each request still pays a `sync_to_async` bridge per middleware on the way in and out — even with async views. The Phase 7 follow-up must audit the middleware stack and either upgrade/replace the sync-only entries, or accept a residual per-request bridge cost. This PR does not block on that audit but the PR description must call it out so Phase 7 doesn't underestimate the work.

**`select_related` / `prefetch_related` under async iteration.** The draft history query uses `.select_related("daily_review").prefetch_related("time_blocks")`. Materialising via `[s async for s in qs]` evaluates both correctly — `async for` triggers the queryset's `__aiter__` (`query.py:389`), which honours the prefetch cache identically to sync iteration. Confirmed in Django 5.2.12 source.

**openai SDK version compatibility.** `pyproject.toml` pins `openai>=2.8.1`. `AsyncOpenAI` has been available since `openai>=1.0`. The `timeout=` per-call parameter and `openai.APITimeoutError` exception are identical across sync and async paths in all `openai>=1.x` releases. Low risk.

**`LLM_DRAFT_CAPTURE_PROMPT_PATH` keeps sync file I/O — intentional.** Inside `run_draft` ([service.py:255-268](backend/ai/service.py#L255-L268)) there is an `os.open(..., O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW, 0o600)` + `os.fdopen(fd, "w").write(user_message)` block guarded by `settings.LLM_DRAFT_CAPTURE_PROMPT_PATH`. This is a dev/test-only capture mechanism used by `frontend/scripts/playwright/draft-prompt-history-suffix.mjs`; the Django system check `ai.E002` blocks startup under `DEBUG=False` when the env var is set, so it cannot reach production. **Leave this block as sync** — the open + write against a local file is microseconds, and inside an async coroutine it blocks the event loop only for that brief window. Converting to `aiofiles` (new dependency) for a dev-only path is not worth the surface area. Mention this explicitly in the PR description so a "make all I/O async" review nitpick gets resolved up-front.

**Test-suite mock-pattern churn.** All six AI test files require `async def create` or `async def _run` changes. Plus the cache-incr test ([test_ai_views.py:614](backend/tests/test_ai_views.py#L614)) needs `cache.incr` → `cache.aincr` + async raiser. The existing hand-rolled fake pattern is simple enough that this is mechanical. Run the verification grep in the Verification section after edits to catch any missed mock.

**`request.user` resolution.** `SimpleLazyObject` resolution via `await request.auser()` is required (D0). Every implicit `request.user` / `request.user.id` access in async context raises `SynchronousOnlyOperation`. Audit all 22 `request.user` sites in `views.py` during the conversion. `@login_required` itself supports async views in Django 4.1+ but does not eagerly populate `request.user` for async — `await request.auser()` must be explicit.

**Prior async views in codebase:** There are **none**. As of this writing, every view in `backend/` is a sync `def`. This PR introduces the first async views. The Django URL router supports mixed sync/async views out of the box (Django 4.1+). Middleware stack is sync-only-tolerant under WSGI; ASGI behaviour is gated by the D5 audit.
