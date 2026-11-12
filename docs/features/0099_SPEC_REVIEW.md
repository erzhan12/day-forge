# 0099 baseline spec review items

Spec miners left the items below out of `openspec/specs/` because the behaviour looked accidental, untested, or contradicted the docs. Each needs a decision: fix the code (then add a spec delta), fix the docs, or accept the behaviour and add a requirement. "Untested" lines list behaviour that is specified but has no test anchor.

Line numbers refer to commit 81b2940.

## export (daily-export, mcp-server)
- export_token_api.py:51-54,67-70 ScheduleChanged branch on token create/revoke untested, response untraced.
- export_auth.py:33-35 `Bearer ` prefix case-sensitive, token whitespace-stripped; untested.
- mcp_server/app.py:18,53 DATE_RE shape-only: 2026-02-30 goes upstream -> "day-forge error 400".
- mcp_server/app.py:21-26 STATUS_ERRORS maps 404/429 that export view never returns; docs/mcp.md lists them as live.
- daily_export.py:82 build_export_report docstring says it backs JSON; export_api.py:83-95 builds JSON itself.
- JSON block order unspecified (read_schedule_day order vs Markdown re-sort).
- docs/mcp.md "never logs the token" — nothing enforces it (no logging at all).
- MCP disallowed Host response unverified; only Origin 403 specified.
- Untested: DAYFORGE_API_BASE precedence, MCP_REQUEST_TIMEOUT<=0, MCP_PORT range, allowlist parsing, 0.0.0.0 bind.
## analytics
- analytics/views.py:337-349 review-id notes route validates body before ownership: other user's id + bad body -> 400 not 404.
- analytics/admin.py:6-29 DailyReviewAdmin keeps notes editable, no has_*_permission override; other day/policy admins are inspection-only (test_admin.py:29-41). Possibly accidental.
- test_analytics_views.py:533-542 docstring says compute_review_stats defaults to server time; services.py:59-60 defaults to user_local_now.
- Untested: stale-but-valid expected_revision 409 on mark-reviewed, 404 missing/other-user schedule, 400 bad date, non-string notes 400, empty notes clears, review cascade delete, admin display fields.
## ai/draft, ai/config
- ai/views.py:461 draft get_or_create Schedule before 409/422 checks — rejected draft may leave an empty row. Unspecified.
- ai/views.py:768 vs service.py:262 — 503 (AI disabled) still consumes a draft rate-limit token; pinned by test_provider_failure_does_increment. Possibly accidental; docs/api.md:488 silent on it.
- ai_generate_draft docstring "10/hr" is the default, not fixed.
- Untested: over-long draft explanation, history window bounds at view level, title trim, under-lock category re-check, unmapped AI error -> 500, provider call args (timeout/json/temp 0), whitespace LLM_API_KEY, LLM_MAX_EXPLANATION_CHARS<=0, 503/504/502 detail text.
## schedules/categories
- categories.py:132 vs :159 duplicate-label check: create trims+casefolds, update uses label__iexact untrimmed; DB constraint Lower(Trim(label)) catches the rest as IntegrityError -> 400.
- category_api.py rate-limit budget consumed before body parse / lookup: invalid JSON, 400 and 404 still count. Docs silent.
- 409 schedule_changed from category views on write contention (category_api.py:32, mutations.py:95-102) untested; docs/api.md:56 implies it.
- checks.py:87 W002 silent when default cache has no BACKEND key — test_checks.py:232 calls it a "known gap".
- Untested: GET shape over HTTP, label >64 over HTTP, _slugify fallback/32-char cut, real duplicate PATCH, swap 400 errors.body, rate limit <=0 import error, DB constraints (one sink/default, sink slug, unique label), nonexistent-id PATCH/DELETE.
## schedules/revisions
- mutations.py:184 vs :46 ScheduleChanged.snapshot set on stale conflict but never serialized; dead attribute.
- api.py:178,231,301,402,525 manual endpoints never catch PersistenceError -> row-level IntegrityError past planner becomes 500, not 400 (only ai/views.py:420 catches). Possibly bug.
- RULES.md:16 "retry at most three times" vs code: 3 attempts total (2 retries). Doc wording fix.
- common/middleware.py:26-30 identity check only when X-Schedule-User present; header-less write passes. RULES.md:17 reads as if every write carries it.
- Untested: single attempt inside outer atomic, non-busy OperationalError propagates, user_write_lock DoesNotExist, precondition rollback, restore proof bad id 400, PersistenceError wrapping, remap order, exact stale detail string, updated_at sync on create.
## schedules/blocks, day-window, schedule-page
- docs/api.md:11 says block times HH:MM; time_validation.py:15 strptime accepts unpadded "9:5" (pinned by test_time_validation.py:76). Window endpoint strict (window.py:31). Same in templates.
- models.py:47 docstring says every forward edit calls mark_active_on_edit; code only on non-empty diff (matches RULES.md:21). Docstring fix.
- Login/logout behaviour (invalid creds, CSRF, logout) owned by no spec yet.
- Untested: no-op PATCH/reorder keeps status, reorder 100-entry cap and per-entry errors, PATCH title/is_completed validation.
## ai/chat, chat-mutations, chat-intents
- chat_requests.py:87 replayed receipt rebuilt without headers: replayed 429 lacks Retry-After. Likely bug.
- ai/views.py:1158-1166 continuation reclassified as `new`: first provider reply never audited; both calls share one rate-limit token.
- Cancel and unexpected non-AI exceptions write no audit row.
- Empty LLM_API_KEY: chat still creates Schedule row, spends token, writes failure audit, stores 503 receipt; project.md says simply "return 503".
- AI create/edit partly outside window is clamped (planning.py:45), not skipped; docs/api.md:681 says skipped actions reported via outcomes. No chat test.
- relative_add_guard.py:204 plain regex for add verb vs _active_request_index ignoring verbs in block titles — inconsistent.
- "Task/calendar text never reaches LLM": only enforcement in backend/ai is masking non-manual block titles; no enforcement point for Todoist/Habitica text (they are simply never referenced).
- RULES.md:3 calls server-owned pending intent "proposed"; RULES.md:66 + code show it implemented.
- Untested: audit-write failure non-fatal, provider call params, replay of stored 429, lease expiry formula, API key absent from logs on client-init failure.
## integrations/todoist
- todoist_sync/views.py:143-148 failed re-verify reports account_state "connected" when row exists; untested.
- schemas.py:58,69 length check on unstripped token, stored value stripped.
- views.py:89-100 "Todoist error" 500 fallback unreachable + untested.
- cache.py:9-11 and project.md say invalidate_tasks uses account.save(); code uses QuerySet.update(updated_at=now) (common/integration_cache.py:31).
- docs/api.md:1349 cache key omits filter scope (exact/with_overdue) and order (tz before date).
- docs/api.md:1337,1398 say all non-2xx are {"errors":{"detail"}}; resource errors also carry code+meta, 400s carry per-field keys.
- Privacy "task text never sent to LLM": no enforcement/test, just absence of imports.
- Untested: 500 on encryption failure during save, TIMEOUT/TTL <=0 import errors, admin read-only.
## integrations/habitica
- habitica_sync/service.py:94-95 _normalize_due_date takes first 10 chars of timestamp = Habitica's date, not user-local; may misfile todos near midnight. Likely bug.
- habitica_sync/service.py:228 complete_task checks HTTP status only, ignores success:false envelope (reads do check).
- views.py:116-120 failed connect while connected reports account_state "connected"; untested.
- views.py:73-81 generic 500 fallback unreachable/untested.
- docs/api.md:1052-1064 tasks example lacks meta{account_state,resource_state}; :1017-1020 POST errors omit 413 + 500; :1022 errors also carry code+meta.
- Untested: DELETE account, complete 503 no-account, admin read-only, TIMEOUT/TTL<=0 import errors, field strip/128 cap, privacy (absence of imports only).
## platform (security, frontend-release, legal-pages)
- CLAUDE.md/project.md "legal pages do not extend base.html" true, but they extend templates/legal/_layout.html (inline CSS + contact fallback live there). Doc precision.
- Anonymous API write: 401 session_invalid / 409 frontend_outdated / 403 CSRF may fire before login redirect; unspecified.
- Dev mode skips only FrontendVersionMiddleware; ReleaseInertiaMiddleware still runs inertia stale check on GET/HEAD.
- Untested: RuntimeError on DEBUG=0 + empty secret, ALLOWED_HOSTS/CSRF origin parsing (no trim), HSTS/secure cookies/SameSite/nosniff, CSRF_COOKIE_HTTPONLY=False, release version pattern rejection, parse_json_object max_bytes=None.
## integrations/google-calendar
- test_ai_service_chat.py:1195 sets origin="google" (not a model choice; real value "calendar"); passes only because redaction applies to any non-manual origin. Test fixture fix.
- views.py:112-114 reconnect w/o access token keeps old token but sets expiry None -> forces refresh next fetch (harmless).
- docs/api.md:1187-1189 omits primary-calendar-id identity fallback (service.py:259-266); :1229-1256 example omits meta.
- project.md GOOGLE_CACHE_TTL_SECONDS key description incomplete (also date, tz, v2 namespace).
- Untested: scope whitespace split, admin read-only, all-accounts-failed resource_state, TTL/TIMEOUT<=0, access_type/prompt params, per-account unexpected exception -> unavailable, refresh transport error mapping, failed fetch not cached.
## integrations/caldav
- calendar_sync/travel_rules.py:212-216 100-rule cap not atomic (code admits it).
- calendar_sync/views.py:94-105 "Apple Calendar error" 500 unreachable + untested.
- docs/api.md:931 says date YYYY-MM-DD; date.fromisoformat (views.py:189) also accepts 20260507, 2026-W19-4.
- docs/api.md:1111 limits travel-rule category to 4 fixed slugs; code accepts "" or any user category slug.
- docs/api.md:923 + project.md cache key description incomplete (tz + v2 namespace).
- backend/ai/checks.py:18 comment points at removed calendar_sync.checks._INEFFECTIVE_CACHE_BACKENDS; now common/integration_checks.py::INEFFECTIVE_CACHE_BACKENDS.
- Untested: connect 500 on encryption misconfig, TIMEOUT/TTL import guards, admin read-only, connected-state on failed reconnect, event sort + out-of-day window guard, "(no title)"/calendar-name fallbacks.

## cross-cutting (all integrations)
- docs/api.md: every integration section says non-2xx = {"errors":{"detail"}}; resource errors also carry code+meta (common/integration_response.py). One shared doc fix.
- Failed re-connect while connected reports account_state "connected" (all 3 task/calendar integrations); untested everywhere.
- Unreachable generic 500 fallbacks in todoist/habitica/caldav views.
## frontend (schedule-page, undo-and-drag, focus-indicator, external-sources, chat-ui)
- PRIVACY DOC: project.md:74 says chat thread in-memory per tab, no server persistence; code stores unresolved request body incl. full transcript in sessionStorage (utils/chatRequestRecovery.ts) and server keeps ChatRequest (ARCHITECTURE.md:47).
- utils/desktopNotificationCopy.ts:16 desktop notification body includes start/end clock times; PiP "no times" privacy rule does not cover desktop notifications. Confirm intended.
- composables/useChat.ts:262 writer busy -> executeTurn returns silently; user text neither appended nor kept. UX bug?
- composables/useDraft.ts:55 409 "Schedule already has blocks…" copy unreachable (bare-409 branch returns first).
- composables/useFocusIndicatorController.ts:130 always errorState:false -> view error/Retry state dead in production.
- Not mined yet: Settings/Analytics/Login pages, theme, daily export dialog, release notice, AddBlockForm/GapSlot/timeline, task/calendar panel components, CommandBar suggestions.
- Untested: undo "Failed restore" schedule_changed path.

## templates (templates, rules, preferences)
- docs/api.md says template block times use the HH:MM regex; code uses strptime("%H:%M"), which accepts "9:5" (same as schedule blocks).
- seed_templates inserts rule priorities 10 and 5 without renumbering and skips window/category validation for template blocks; a seeded user has non-contiguous priorities until the next API create/delete.
- Rule PATCH can leave priority gaps by design (pinned by a test); "priorities are 0..N-1" holds only after create/delete.
- template_detail checks ownership before taking the lock; a concurrent DELETE still returns {"ok": true}.
- get_user_preferences creates the default row on read with a bare get_or_create (no user lock).
- Empty category catalog + template block without category raises RuntimeError (pinned by test_empty_categories_fallback_raises) instead of a 4xx.
- Rule create counts existing rules via request.user, not the locked user object (same user; harmless).
- Untested: PUT into an occupied slot (409), 100-rule cap, template name blank/>100 chars, 50-block cap, invalid rule field types, empty rule PATCH, sink slug stored on save, Template/Rule admin view-only, Settings list ordering.

## Ownership decisions taken during mining
- "Task and calendar text never reaches the LLM": integration specs no longer restate it. Title masking is owned by ai/chat ("Protected block titles are masked for the provider") and ai/draft ("Imported block titles stay out of draft prompts"). Todoist and Habitica task text has NO enforcement point: backend/ai simply never imports those apps. Consider an import-boundary test before specifying it.
- Duplicate owners kept on purpose: reorder atomicity (schedules/blocks validation, schedules/revisions atomicity); auto_draft_pending (ai/config and schedules/schedule-page). Session identity middleware is owned by platform/security only.
- Scenarios without a Tests: line: 45 of 1086.
- Coverage: shipped without the remaining frontend surface (100 frontend/src files uncited, incl. Settings, Analytics and Login pages, daily export dialog, timeline components, task/calendar panels, CommandBar). Add specs for these when a feature next touches them. Backend: only boilerplate is uncited (urls.py, asgi.py, wsgi.py, manage.py, ai/admin.py, preference_defaults.py).
