# 0015 — Code Review: Migrate cache to Redis

**Reviewed:** working-tree implementation vs `docs/features/0015_PLAN.md` (round 2, after follow-up fixes)  
**Method:** Plan checklist, diff inspection, targeted + full backend pytest, `ruff check` on touched modules.

## Verdict: ✅ Clear — ready to merge

All four plan phases are implemented. The rate limiter uses atomic sync `cache.incr` (via `sync_to_async`), not `cache.aincr`, so the Redis migration delivers cross-worker correctness. Round-1 documentation nits are addressed. **475** backend tests pass; **no open findings**.

---

## Round 2 — fixes verified

| Prior finding | Status |
|---------------|--------|
| **RULES.md** missing Redis / sync-`incr` guidance | ✅ **Resolved** — new § “Rate-limit increment: sync `cache.incr`, not async `aincr`” documents the `sync_to_async(cache.incr)` pattern, TTL footgun, `ai.E001`, and the FileBased vs per-process distinction (`RULES.md` lines 125–128). |
| **N3** — `CLAUDE.md` bundled FileBased with “per-process” | ✅ **Resolved** — Production Deployment bullet now reads: `LocMemCache` / `DummyCache` are per-process; `FileBasedCache` is non-atomic across workers. |
| **N1** — compose `depends_on` without Redis healthcheck | Accept-as-is — `docker compose up` still uses plain `depends_on`; lazy connect on first cache op is fine for dev. Add `healthcheck` + `condition: service_healthy` only if cold-start connection errors show up. |
| **N2** — `.env.example` ships concrete `REDIS_URL` | No change needed — consistent with `ai.E001`; `docker compose` stack includes `redis` + `REDIS_URL` on `web`. |
| Optional Redis two-worker CI smoke | Still out of scope (unchanged). |
| Stale `0009` plan references to `cache.aincr` | Still out of scope for 0015; optional doc sweep later. |

---

## Plan fidelity

| Phase | Status | Notes |
|-------|--------|-------|
| **1 — Config + dependency** | ✅ | `redis>=5.0` in `pyproject.toml` / `uv.lock`; `REDIS_URL` → `RedisCache` + `KEY_PREFIX: dayforge`; LocMem fallback when unset. `REDIS_URL.strip()` avoids blank-LOCATION misconfig. |
| **2 — `ai.E001` hardening** | ✅ | `_INEFFECTIVE_CACHE_BACKENDS` (LocMem / FileBased / Dummy); fires when `LLM_API_KEY.strip()` is non-empty, **independent of `DEBUG`**; Redis + PyMemcache silent. Check message distinguishes per-process vs non-atomic FileBased. |
| **3 — Tests** | ✅ | FileBased + Dummy cases; shared-backend docstring; Memcached silence; key-shape regression; TTL preservation; session `_pin_test_cache_backend`; `TestCacheBackendConstruction` (4 cases). |
| **4 — docker-compose + docs** | ✅ | `redis:7-alpine`, `REDIS_URL` on `web`, `depends_on`; `.env.example`, `CLAUDE.md`, `README.md`, `.claude/rules/project.md`, `RULES.md`; `_consume_rate_limit` docstring. |

**Intentional dev-policy regression (per plan):** AI-enabled local dev with `LLM_API_KEY` set and no `REDIS_URL` fails `manage.py check` on LocMem — correct forcing function.

---

## Correctness

### Rate limiter path (critical)

`_consume_rate_limit` in `backend/ai/views.py`:

- Window anchor: `await cache.aadd(key, 1, 3600)` ✅  
- Increment: `await sync_to_async(cache.incr, thread_sensitive=True)(key)` ✅ — atomic Redis `INCR`, TTL preserved.  
- Reseed: `except ValueError → await cache.aset(...)` ✅  

`test_increment_preserves_window_ttl`, `test_cache_incr_value_error_reseeds_counter`, and `test_counter_stored_under_expected_key` cover TTL, reseed, and key shape on the pinned LocMem suite.

### Settings / env / check

- `REDIS_URL = os.environ.get("REDIS_URL", "").strip()` — safe import-time default. ✅  
- `KEY_PREFIX: dayforge` namespaces logical keys transparently to `cache.get`. ✅  
- `ai.E001` exact backend membership; whitespace-only `LLM_API_KEY` ignored. ✅  

No API payload / casing alignment issues (cache-only feature).

---

## Tests

| Area | Tests |
|------|--------|
| `ai.E001` ineffective backends | LocMem, FileBased, Dummy; DEBUG=True; whitespace key silent |
| Shared backends silent | Redis, PyMemcache |
| Settings construction | Redis + prefix; unset/whitespace → LocMem; stripped LOCATION |
| Rate limit views | 429 budget; `ai_cmd_rl:<user_id>`; TTL preservation; incr `ValueError` reseed |

**Isolation:** Session `override_settings` LocMem pin; per-test `CACHES` overrides in check tests; no live Redis in unit suite. ✅  

**Acceptable gap:** No CI Redis / two-process fanout test (plan Phase 3); enforcement via `ai.E001` + sync `incr` semantics.

**Low fragility:** `test_increment_preserves_window_ttl` uses LocMem `_expire_info` — documented, Django-internal.

---

## Style, structure, docs

- Conventions match the rest of the codebase. ✅  
- `RULES.md`, `CLAUDE.md`, `README.md`, and `project.md` are aligned on **Redis when AI is enabled**. ✅  
- Legacy names (`error_locmem_cache_with_ai_in_production`, `TestLocmemCacheProductionError`) — harmless.  
- No over-engineering; duplicated ineffective-backend tuple in `ai` vs `calendar_sync` is intentional.

---

## Findings

**No open High / Medium / Low / Nit items for merge.**

Optional follow-ups (non-blocking):

- Compose Redis `healthcheck` if cold-start races appear in practice.  
- Redis-backed two-worker rate-limit smoke in CI.  
- Update `docs/features/0009_async_ai_views_PLAN.md` to reflect sync-`incr` bridge (historical plan drift).

---

## Verification evidence (round 2)

```text
uv run pytest backend/tests/ -q          → 475 passed
uv run pytest backend/tests/test_checks.py \
  backend/tests/test_settings_validation.py::TestCacheBackendConstruction \
  backend/tests/test_ai_views.py::TestRateLimit -q  → 23 passed
uv run ruff check (touched backend modules) → clean
```

---

## Summary

Feature 0015 is complete and correct: shared Redis for rate limits (and CalDAV cache perf), hardened `ai.E001`, deterministic test pinning, and operator docs including the critical **sync `incr` / not `aincr`** rule in `RULES.md`. Round-1 review nits are closed. Safe to merge after manual smoke with `REDIS_URL` + Redis when exercising AI (`docker compose up` provides both `web` and `redis`).
