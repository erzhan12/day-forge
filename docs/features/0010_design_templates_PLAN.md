---
name: 0010 - Selectable design templates
description: Add per-user UI design templates, including a Strategic Board-inspired visual style and a Settings selector for switching between Classic, Strategic, and Light Premium.
type: feature-plan
---

# 0010 - Selectable design templates

## Context

The user asked: "Посмотри сайт strategicboard.ru, мне понравился стиль дизайна этого сайта. Можем ли мы взять его и применить для нашего сайта. Также я хочу чтобы была возможность выбирать шаблон дизайна. Задавай вопросы интерактивно."

After reviewing `strategicboard.ru`, the target design influence is:

- dark smoky blue/black background with soft glow and subtle grid/noise atmosphere;
- serif display headings with a premium editorial feel;
- translucent/glass-like panels;
- rounded pill buttons and muted borders;
- cold blue active accents;
- calm, spacious visual hierarchy.

This feature should not copy source, assets, textures, or exact branding from `strategicboard.ru`. It should recreate the feeling with original Day Forge CSS tokens and component styling.

Clarified decisions:

- Design selection is stored per user in the backend profile/preferences, not only in browser storage.
- First release includes three design templates: `Classic`, `Strategic`, and `Light Premium`.
- The login screen always uses the `Strategic` style because no authenticated user preference is available before login.
- The first implementation should be a real theme/template foundation, but not a full layout engine. Themes may adjust colors, typography, spacing, surfaces, and small layout tokens; they should not change schedule behavior or introduce alternate app flows.

## Existing code shape

Frontend:

- `frontend/src/app.ts` mounts the Inertia app and has no shared layout/theme provider.
- `frontend/src/app.css` contains the only global CSS reset and base body colors.
- Pages import `../app.css` directly:
  - `frontend/src/pages/Schedule.vue`
  - `frontend/src/pages/Settings.vue`
  - `frontend/src/pages/Login.vue`
  - `frontend/src/pages/Analytics.vue`
- Most visual styles live in scoped Vue CSS with hard-coded hex colors.
- High-impact themed components include:
  - `frontend/src/components/DateNavigator.vue`
  - `frontend/src/components/TimeBlock.vue`
  - `frontend/src/components/GapSlot.vue`
  - `frontend/src/components/AddBlockForm.vue`
  - `frontend/src/components/CommandBar.vue`
  - `frontend/src/components/ChatSidebar.vue`
  - `frontend/src/components/DraftBadge.vue`
  - `frontend/src/components/RegenerateDraftButton.vue`
  - `frontend/src/components/CompletionBar.vue`
  - `frontend/src/components/CategoryBreakdown.vue`
  - `frontend/src/components/SkippedTasks.vue`
  - `frontend/src/components/TemplateEditor.vue`
  - `frontend/src/components/RulesList.vue`
  - `frontend/src/components/UndoToast.vue`
- `frontend/src/utils/categoryColors.ts` is the current single source of truth for category swatches used by schedule and analytics.
- `frontend/src/composables/useHttp.ts` provides `requestJson()` for CSRF-aware JSON API calls.

Backend:

- `backend/templates_mgr/models.py` owns the existing user-scoped settings-like data: `Template` and `Rule`.
- `backend/templates_mgr/views.py::settings_view` passes initial `templates` and `rules` props to the Inertia Settings page.
- `backend/templates_mgr/api.py` contains the established JSON API style for user-owned settings data.
- `backend/schedules/views.py::schedule_view` passes the Schedule page props.
- `backend/analytics/views.py::analytics_view` passes the Analytics page props.
- `backend/schedules/views.py::login_view` renders the Login page.
- `backend/day_forge/urls.py` wires page and API routes.
- There is no existing user profile or preferences model.

## Phase 1 - Backend preferences data

Files:

- Modify `backend/templates_mgr/models.py`
- Create a new Django migration under `backend/templates_mgr/migrations/`
- Modify `backend/templates_mgr/admin.py` — register `UserPreferences` for the Django admin in v1 (not optional). Minimum useful surface: list view with `user` and `theme` columns, `list_filter = ("theme",)`, `search_fields = ("user__username",)`, and `readonly_fields = ("created_at", "updated_at")`. Reasoning: a per-user prefs row is exactly the kind of state that gets pinged during support/debug — "what theme is user X actually on?" — and a 5-minute admin registration pays back the first time someone has to write `UserPreferences.objects.get(user__username="…")` in `manage.py shell`. Optional sugar: inline the prefs on the `User` admin via `inlines = [UserPreferencesInline]`.
- Add tests in `backend/tests/test_user_preferences_api.py` or `backend/tests/test_design_preferences.py`

### Model

Add a small `UserPreferences` model in `templates_mgr`. Keeping it in this app is consistent with the current `/settings/` surface, avoids adding a new Django app for one field, and keeps templates/rules/preferences together as user-controlled configuration.

**Forward-pointing note**: this co-location is defensible for v1 (one preference field, all user-controlled config). If preferences grow beyond UI theme — notification settings, locale, time format, etc. — `templates_mgr` becomes a junk drawer of unrelated concerns under a misleading name. The cleanup path is either (a) split into a new `users` or `preferences` app, or (b) rename `templates_mgr` to something more general. Don't preempt; add a `tasks/todo.md` backlog item when the second preference field is added so the decision is made deliberately, not by accretion.

**Admin placement intuition**: a staff user looking for "user preferences" in the Django admin will likely look under `Users`, not `Templates`. Reduce that friction by registering `UserPreferences` as an inline on the `User` admin (see the `UserPreferencesInline` sugar mentioned in Phase 1's admin file). The standalone `UserPreferences` admin entry under `Templates_mgr` should still exist for direct querying, but the inline-on-User-admin path is the discovery affordance that matches staff intuition. This is independent of the model's app-level placement, which is constrained by the v1 co-location decision above.

Fields:

- `user`: `models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferences")`
- `theme`: `models.CharField(max_length=32, choices=Theme.choices, default=Theme.CLASSIC)` where `Theme` is a `models.TextChoices` enum:
  ```python
  class Theme(models.TextChoices):
      CLASSIC = "classic", "Classic"
      STRATEGIC = "strategic", "Strategic"
      LIGHT_PREMIUM = "light_premium", "Light Premium"
  ```
  Use `TextChoices` (not a raw `choices=` tuple) so the IDs are referenceable as `Theme.STRATEGIC` from Python code instead of bare strings — this matches the pattern used in `schedules.models.Schedule.Status` and `templates_mgr.models.Template.Type` elsewhere in the codebase. `max_length=32` leaves headroom for future theme IDs without a schema migration; the longest current value (`light_premium`) is 13 chars.
- `created_at`: `models.DateTimeField(auto_now_add=True)`
- `updated_at`: `models.DateTimeField(auto_now=True)`

Default theme is `Theme.CLASSIC` for authenticated app pages unless the user changes it. This preserves current behavior as the fallback.

### Serialization helper

Add a small helper near the model/API layer that returns the frontend preference shape:

- `theme`: current theme id.
- Optionally `available_themes` should not be serialized from the backend if the frontend owns the theme registry. Prefer frontend-owned labels and backend-owned validation IDs to avoid duplicating display metadata.

### Preference lookup algorithm

Use one canonical lookup path for page props and API responses:

1. Call `UserPreferences.objects.get_or_create(user=request.user, defaults={"theme": Theme.CLASSIC})`. Use the enum, not the bare string `"classic"`, in every Python code path. Rationale: if a future refactor renames `Theme.CLASSIC` (or its value), a string literal silently goes wrong and surfaces only when the typo (`"classsic"`) hits validation; the enum reference fails at import time. Wire-format strings in JSON request/response examples and CSS selectors (e.g. `html[data-theme="classic"]`) stay as strings — they're not Python identifiers.
2. **Normalize the stored `theme` value before returning.** Django's `choices=` validates form/serializer input but not direct ORM writes, fixture loads, or rows persisted before a choice value was retired. A row with `theme="bad"` (legacy, fixture typo, manual SQL edit) would otherwise propagate to both `<html data-theme="bad">` and the `ui_preferences` prop, leaving the app with no matching CSS tokens and broken styling. If the persisted value is not one of `{classic, strategic, light_premium}`, treat it as `classic` in the returned value without rewriting the DB row (silent self-healing on read is safer than a write-on-read side effect; an admin can clean the row up explicitly).
3. **Return a small read-only DTO, not the ORM instance.** Use a `dataclasses.dataclass(frozen=True)` with the normalized fields:
   ```python
   @dataclass(frozen=True)
   class UserPreferencesDTO:
       theme: str  # always one of the recognized IDs
   ```
   This is non-negotiable: returning the ORM instance with a normalized `.theme` attribute creates a write-on-read hazard. Any caller that later calls `.save()` on the instance (intentionally for an unrelated field, or accidentally) would write the normalized value back to the DB, defeating the corruption-healing design. A frozen DTO makes the contract structural — there is no `.save()` to misuse, and the type system forbids any mutation.

`get_or_create` is required (not "try fetch, else insert") because two concurrent first-visit requests — e.g. a Schedule page render plus an Inertia preflight on the same cold session — would both miss the row and both `INSERT`, hitting the OneToOne unique constraint on the second. `get_or_create` is atomic at the DB level via `IntegrityError` rescue, so the race resolves correctly.

This may create a preference row on first authenticated page visit. That is acceptable because it is user-owned configuration and avoids every page handling a missing preference.

**Normalization contract**: the value returned by `get_user_preferences(user).theme` is guaranteed to be one of the recognized theme IDs. Every call site (page props, `template_data`, API response serializer) can pass `prefs.theme` directly without re-checking — the helper is the choke point. The PATCH handler is the one place that must NOT use the DTO for its update logic — it fetches the raw `UserPreferences` row directly (separate ORM call) so it can compare against the raw `theme` column and heal corruption (see Phase 2 PATCH algorithm step 8). The DTO is for read paths (page props, GET responses); the raw row is for write paths.

Backend tests for the helper:

- Returns `classic` (the normalized fallback) when the DB row holds an invalid value, AND the DB row is unchanged after the call (no write-on-read).
- Return type is the frozen DTO, not the ORM instance (assert `isinstance(result, UserPreferencesDTO)` and `not isinstance(result, UserPreferences)`).

## Phase 2 - Backend API and Inertia props

Files:

- Modify `backend/templates_mgr/api.py`
- Modify `backend/templates_mgr/views.py`
- Modify `backend/schedules/views.py`
- Modify `backend/analytics/views.py`
- Modify `backend/day_forge/urls.py`
- Modify `backend/templates/base.html` (server-rendered `data-theme` — see "Server-rendered `data-theme`" subsection below)
- Modify `docs/api.md` — add the `/api/user/preferences/` endpoint reference following the existing per-endpoint structure (path, method, auth, path params, request body schema, success response shape, error responses, headers). Include the `Cache-Control: private, no-store` contract explicitly so it's not lost in code. Add a short note on the unknown-field-ignore semantics and the empty-body "No editable fields supplied." error so client implementers don't have to read the source to learn the contract. Previous AI feature phases (0007, 0009) updated `docs/api.md` in lockstep with the endpoint; do the same here. **Auth-failure response shape**: be accurate, not aspirational. `@login_required` returns a `302` redirect to the login URL for browser-style clients, NOT a JSON `401`. Document what Django actually returns — the existing `docs/api.md` "Conventions" section already states "unauthenticated requests receive `302` → `/accounts/login/`"; the per-endpoint section for `user_preferences` should be consistent with that, not introduce a divergent 401 expectation that `requestJson` cannot satisfy.
- Add/update backend tests

### API endpoint

Add a user-scoped endpoint:

- `GET /api/user/preferences/`
- `PATCH /api/user/preferences/`

The endpoint can live in `backend/templates_mgr/api.py` and be wired from `backend/day_forge/urls.py`.

Validation rules:

- Require authentication via Django session, matching the existing API surface (`templates_collection`, `rule_detail`, etc.) — `@login_required` + CSRF via `X-XSRF-TOKEN` header per the project-wide convention documented in `docs/api.md`. **Do not introduce a Bearer-token or API-key auth model for this endpoint** — the entire app's API surface uses session+CSRF, and a per-endpoint divergence would surprise both the frontend (`requestJson` is built around CSRF) and future maintainers. If a Bearer model is ever wanted, it's a project-wide decision, not a one-endpoint shortcut.
- `GET` returns the current preferences, creating defaults if needed.
- `PATCH` accepts only editable preference fields for now.
- `theme` must be one of `classic`, `strategic`, or `light_premium`.
- **Unknown fields are silently ignored** — matching the existing `rule_detail` PATCH pattern in `backend/templates_mgr/api.py`. The parser extracts only recognized fields; unrecognized keys are discarded without error. This keeps the endpoint forward-compatible (a client sending a future preference field to an older server does not get a 400) and is consistent with every other PATCH endpoint in the project.
- An empty PATCH body (or one containing only unrecognized fields) returns `{"errors": {"body": "No editable fields supplied."}}` — same wording as `rule_detail`. This provides typo detection for the current field set: a client that sends `{"Theme": "strategic"}` (wrong case) gets a 400, which is better than silently accepting a no-op.
- Invalid JSON should return `{"errors": {"body": "Invalid JSON."}}`.
- Invalid `theme` value should return a field-specific error: `{"errors": {"theme": "Invalid theme."}}` (or similar).
- **Every response from `GET` and `PATCH` must set `Cache-Control: private, no-store`** — including error responses (400 on invalid JSON, 400 on invalid theme, 400 on "No editable fields supplied", 413 on oversized body, 405 on unsupported method, 401/302 on unauthenticated). The body of any of these contains per-user state or hints at it; a misconfigured CDN or proxy that caches a 400 with `{"errors": {"theme": "Invalid theme. Got: \"strategic-2\""}}` could leak one user's attempted preference value to another. Implementation: do NOT set the header per-return-path — that's how regressions happen. Wrap every return with a small response helper or decorator that sets the header uniformly:
  ```python
  def _prefs_response(payload, status=200):
      resp = JsonResponse(payload, status=status)
      resp["Cache-Control"] = "private, no-store"
      return resp
  ```
  Every `return` in `user_preferences` (success, validation errors, oversize, unknown method) goes through `_prefs_response(...)`. The cache-header test in P7 must exercise at least one error path (e.g. invalid theme) in addition to the success path so a future implementer who adds a new error branch and skips the helper gets caught.
- **Rate limiting is deferred to v1.1.** Add a tracked follow-up to `tasks/todo.md` titled `0010-followup: user_preferences PATCH rate limit (v1.1)` when v1 ships. The deferral is correct (async/sync helper split, `ai.E001` coupling — see below), but the rationale is easy to lose between releases. The follow-up item is what carries it forward. The naive "reuse the AI pattern" wiring does not work as written: `_consume_rate_limit` in `backend/ai/views.py` is `async def` and uses `cache.aadd`/`cache.aincr`, while `templates_mgr/api.py` is sync `def`. Calling the async helper from a sync view requires `async_to_sync()` plus a duplicate sync path or a refactor. Additionally, `ai.E001` only fires when `LLM_API_KEY` is set and only inspects the three AI bucket names — a new `user_prefs_rl` bucket would silently inherit per-process `LocMemCache` semantics in any deployment that doesn't set `LLM_API_KEY`. For v1, accept the unrate-limited PATCH: the endpoint is authenticated, CSRF-protected, low-volume by nature (one PATCH per theme switch, ≤ a handful per user lifetime), and the worst-case abuse is one user thrashing their own preference row. v1.1 prerequisites: (a) extract a shared rate-limit helper in `backend/common/rate_limit.py` with both sync and async entry points wrapping the same cache key scheme, (b) extend `ai.E001` (or add a sibling check) to cover any newly-registered bucket name passed through a registry, (c) add `USER_PREFERENCES_RATE_LIMIT_PER_HOUR` and wire the PATCH handler to it.

Update algorithm for `PATCH`:

1. Reject oversized body using `reject_oversized_body()`.
2. Parse JSON.
3. Validate that the body is an object.
4. Extract recognized fields from the body (currently just `theme`). If the body contains zero recognized fields (empty body or only unknown keys), return `{"errors": {"body": "No editable fields supplied."}}` with status 400.
5. Validate `theme` if present (must be one of the allowed IDs).
6. Fetch or create the authenticated user's preferences.
7. Apply recognized fields to the instance. **A recognized field with the same value as the persisted value is a valid no-op** — e.g. PATCH `{"theme": "classic"}` on a user whose theme is already `classic` must return 200 with the serialized preferences, not 400. The "No editable fields supplied" error is reserved exclusively for case (4) above (no recognized fields in the body at all). Do not conflate "no DB change" with "no recognized fields"; they are different conditions with different responses.
8. **Always persist any validated recognized field, even when it equals the current normalized value.** This is the corruption-healing rule: the helper from Phase 1 normalizes invalid stored values on read (e.g. returns `"classic"` for a `theme="bad"` row) WITHOUT rewriting the DB. If PATCH compares the incoming value against the helper's *normalized* return and skips the write because they match, a PATCH `{"theme": "classic"}` against a corrupted `theme="bad"` row is silently treated as a no-op and the bad value persists indefinitely. Two equivalent ways to avoid the trap:
   - **Compare against the raw DB value, not the normalized return.** Fetch the row, read its raw `theme` column directly, compare to the incoming value, write if they differ. This preserves the optimization for the common case while healing the corrupt case.
   - **Always write recognized fields, no comparison.** Drop the "skip write if no change" optimization entirely. One extra UPDATE per no-op PATCH (cost: negligible — preference PATCHes are low-frequency) in exchange for guaranteed corruption-healing on every write.
   Pick either. Both produce the correct behavior; the second is simpler. Do not retain the "compare against the normalized return" path — it has the bug.
9. Save and return the serialized preferences (the normalized representation from the Phase 1 helper).

Backend tests for this section:

- **No-op success**: PATCH `{"theme": "classic"}` against a user with `theme="classic"` returns 200 and the serialized preferences. Guards against routing the same-value case through the "No editable fields supplied" 400 branch.
- **Corruption healing**: pre-seed a user's DB row with an invalid `theme` value (raw SQL or `UserPreferences.objects.filter(...).update(theme="bad")` to bypass the choices validator), then PATCH `{"theme": "classic"}` and assert (a) response is 200, (b) the DB row's raw `theme` column is now `"classic"`, not `"bad"`. Guards against the normalization-vs-comparison trap above.

### Page props

Add `ui_preferences` to authenticated Inertia pages:

- `backend/templates_mgr/views.py::settings_view`
- `backend/schedules/views.py::schedule_view`
- `backend/analytics/views.py::analytics_view`

The prop shape should include at least:

- `theme`: one of the allowed theme IDs.

Do not add `ui_preferences` to `login_view`; login uses the static Strategic style by frontend convention.

**Resolve preferences exactly once per authenticated page request.** Each of the three views above must look up the user's preferences a single time and reuse the resolved value for both the `ui_preferences` prop AND the `template_data["initial_theme"]` SSR value:

```python
prefs = get_user_preferences(request.user)  # one call, one DB hit
return inertia_render(
    request,
    "Schedule",
    {"ui_preferences": {"theme": prefs.theme}, ...},
    template_data={"initial_theme": prefs.theme},
)
```

Two reasons this matters: (a) calling the helper twice doubles the DB hit per page render for a value that is read on every authenticated page; (b) if a concurrent PATCH commits between the two calls, the SSR `data-theme` and the Vue `ui_preferences` prop would disagree, briefly painting one theme and then transitioning to another — a small but real cross-source inconsistency. Single resolution closes both.

### Server-rendered `data-theme` (FOUC prevention)

The Django HTML template that bootstraps Inertia must server-render the active theme onto `<html data-theme="…">` before any JS runs. Without this, every page load briefly paints the default theme before the frontend reads `ui_preferences` and applies the user's choice — a Strategic user sees a Classic-light flash on every navigation, which is the #1 daily annoyance the feature must avoid.

Mechanism — must use `inertia_render`'s `template_data=` kwarg, not Inertia props alone. Props are JSON delivered to the Vue app; they never reach `backend/templates/base.html`. The base template needs the value before any JS runs, which means it has to come through the Django template context.

Two acceptable wirings:

1. **Per-view `template_data=`** (preferred for explicitness): each authenticated view that calls `inertia_render` passes `template_data={"initial_theme": resolved_theme}`. `inertia-django==1.2.0` exposes this as `render(request, component, props=None, template_data=None)` (see `inertia/http.py:215` in the installed package).

   `login_view` has **three** `inertia_render` call sites ([backend/schedules/views.py:29,36,49](backend/schedules/views.py#L29-L51)) — GET, invalid-JSON POST, invalid-credentials POST. Every one must pass `template_data={"initial_theme": "strategic"}`. Missing any path means a user who submits a bad password sees a Classic-light flash on the error render. The cleanest implementation is a module-level constant `_LOGIN_TEMPLATE_DATA = {"initial_theme": "strategic"}` and a helper `_render_login(request, props)` that passes it on every call — refactor the three call sites through the helper so the rule is enforced by structure, not by reviewer vigilance.
2. **Context processor** (less boilerplate but more global coupling): add `initial_theme` to `backend/day_forge/context_processors.py` alongside `vite_dev_mode`. The processor calls the same `get_or_create` lookup for authenticated requests and falls back to `"strategic"` for the login page. Trade-off: every Django view rendered through any template (not just Inertia) pays the lookup, including admin pages and 404s.

Pick #1 unless the per-view boilerplate becomes >4 call sites; the current AI-feature view count is well under that.

Template change — modify `backend/templates/base.html`:

```html
<html lang="en" data-theme="{{ initial_theme|default:'classic' }}">
```

The `default:'classic'` fallback is deliberate: it makes a forgotten `template_data` produce a Classic-light flash for **every** user (including Strategic users who would notice it instantly), rather than silently masking the missing wiring for the cohort most likely to catch it. Defaulting to `strategic` here would hide regressions from Strategic users (who'd see no flash) while still flashing Classic users.

**Forward-looking note on guest/error templates**: anything else that extends `base.html` without passing `initial_theme` (a 404 page, a 500 page, a future signup or marketing route, a Django admin redirect through Inertia, etc.) will render Classic by default. That is correct *as a regression-detection mechanism* for authenticated views that forget `template_data`. It is **not necessarily the right theme** for a future public-facing page where Strategic might be the intentional brand surface. When such a page is added, decide its theme explicitly via `template_data` rather than relying on the default. The default is a safety net, not a design choice.

**Error templates that do NOT extend `base.html`**: Django's default 404/500 handlers render `404.html` / `500.html`, which in this project may or may not extend `base.html` — verify before P2 ships. If an error template does not inherit from `base.html`, the `data-theme` rule does not apply to it (no template fallback, no `initial_theme` context variable). Decide explicitly per template: either (a) inherit from `base.html` so the same theme rule applies, or (b) accept that error pages have no theme and may visually disagree with the rest of the app. For v1 the safer choice is (a) — inherit from `base.html` so an authenticated user landing on a 500 page still sees their saved theme. Add this to the implementer's pre-P2 inventory step alongside the `inertia_render` grep.

Login is the one place where the fallback would produce the wrong theme — login must always be Strategic, but if `login_view` ever forgot to pass `template_data`, the fallback would silently give Classic. The plan closes this with a `_render_login` helper (see option 1 below) that routes every login render through one call site so the rule is enforced structurally.

Frontend boot must not undo this — see Phase 3 "Theme application algorithm" for the rule that `app.ts` reads the existing `document.documentElement.dataset.theme` instead of forcing a default.

### URL naming

Register the endpoint near templates/rules routes in `backend/day_forge/urls.py`, for example:

- route path: `api/user/preferences/`
- route name: `user_preferences`

Keep the API singular because each user has exactly one preferences row.

**Naming clarity note**: the new path lives next to `/api/templates/` and `/api/rules/`, which serve the `templates_mgr.Template` (schedule template) and `templates_mgr.Rule` models. "Design template" (UI theme) and `templates_mgr.Template` (schedule template) are unrelated concepts that share the word "template." Help future readers by (a) keeping the URL path as `/api/user/preferences/` (not `/api/templates/design/` or similar — the `user/preferences` prefix signals it's a different concern), and (b) adding a one-line comment in `urls.py` next to the route: `# Per-user UI preferences (theme, future settings). Distinct from templates_mgr.Template.` Costs nothing, saves a confused grep.

## Phase 3 - Frontend theme registry and application

Files:

- Create `frontend/src/utils/themes.ts` (theme registry — labels, descriptions, preview tokens)
- Create `frontend/src/utils/theme.ts` (three exports: `isKnownTheme`, `normalizeTheme`, `applyTheme` — see "Theme application algorithm" below for the contract of each)
- Create `frontend/src/composables/useThemeFromProps.ts` (the per-page composable — see "Inertia prop access" below)
- Modify `frontend/src/types/index.ts`
- Modify `frontend/src/app.ts`
- Modify `frontend/src/pages/Login.vue`
- Modify `frontend/src/pages/Schedule.vue` — add `useThemeFromProps()` call in `setup()`. This is the composable-wiring step; visual theming of the schedule surfaces lands in Phase 6.
- Modify `frontend/src/pages/Settings.vue` — add `useThemeFromProps()` call in `setup()`. (The Design selector itself lands in Phase 5; this Phase 3 edit is just the composable wiring.)
- Modify `frontend/src/pages/Analytics.vue` — add `useThemeFromProps()` call in `setup()`.
- Modify `RULES.md` — append the "new authenticated page" rule documented under "Inertia prop access" below (any new authenticated Inertia page must (a) be backed by a Django view that passes `ui_preferences` props AND `template_data={"initial_theme": ...}`, AND (b) call `useThemeFromProps()` in its setup block). RULES.md is the project's living convention doc and is the right home for this rule so it survives session boundaries. **Drift check before merging Phase 3** (and again before merging Phase 5, since the selector lands then): re-read the RULES.md snippet against the final composable signature, the final `useThemeFromProps()` import path, and the final view-side prop shape. If the composable was renamed, the import moved, or the prop shape changed during implementation, update RULES.md in the same commit — do not leave a stale convention doc pointing at an old API.
- Add frontend tests under `frontend/tests/`

### Types and registry

Add frontend types:

- `ThemeId`: `classic | strategic | light_premium`
- `UiPreferences`: object containing `theme: ThemeId`

Add a frontend theme registry with:

- stable id;
- human-readable label;
- short description for the Settings selector;
- **required** preview tokens used by the selector cards: `bgPage`, `bgPanel`, `accent`, and `textPrimary` for each theme. Optional but encouraged: a sample serif/sans label string so the typography difference is visible without committing.

Preview tokens are required (not optional) because the selector's whole job is to let users compare themes without the cost of switching, reloading, and reverting. A label-only selector forces commit-before-evaluate, which is the failure mode the selector exists to prevent.

The frontend registry is the source of truth for display labels. Backend remains the source of truth for allowed persisted IDs.

### Theme application algorithm

Expose two distinct functions — not one — to avoid a contract conflict between value normalization and DOM preservation:

**`isKnownTheme(raw: unknown): raw is ThemeId`**
- Pure type guard. Returns true iff `raw` is one of `'classic' | 'strategic' | 'light_premium'`.
- Used by `useThemeFromProps` (below) to distinguish "valid theme id, apply it" from "absent or unrecognized, preserve current DOM."
- This is a distinct concern from `normalizeTheme`: the guard says "is this safe to use as-is," the normalizer says "give me something safe regardless of input."

**`normalizeTheme(raw: unknown): ThemeId`**
- Pure value normalizer. Maps any input to a valid `ThemeId`.
- If `isKnownTheme(raw)`, return it unchanged.
- Otherwise (missing, null, unknown string) return `'classic'`.
- Has no side effects — does not touch the DOM.

**`applyTheme(id: ThemeId): void`**
- Sets `document.documentElement.dataset.theme = id`.
- Optionally sets a body class only if component CSS cannot reasonably target `html[data-theme]`.
- Always receives an already-normalized `ThemeId`; does not normalize internally.

The reason for the split: `normalizeTheme` maps missing → `'classic'`, which is correct when you have a known initial context (app boot, a successful PATCH response). But in the partial-reload case (see "Inertia prop access" below), calling `applyTheme(normalizeTheme(undefined))` would write `classic` to the DOM and overwrite the currently-correct SSR-rendered theme. The two-function design forces call sites to choose deliberately: either normalize-then-apply, or preserve-current.

Apply the theme:

- **NOT on app boot with a hardcoded default.** The base template (Phase 2) already server-renders the correct `data-theme` attribute on `<html>`. Forcing `applyTheme('classic')` from `app.ts` before page props are read would overwrite the SSR value.
- **On app boot**: read the initial theme from `document.documentElement.dataset.theme` (already set by SSR). If it is a recognized ThemeId, no call to `applyTheme` is needed — the DOM is already correct. If it is missing or unrecognized, call `applyTheme(normalizeTheme(undefined))` to set the safe default. Do not read from `props.initialPage.props.ui_preferences` at boot just to overwrite an already-correct SSR attribute.
- **After a successful PATCH**: do **not** call `applyTheme()` from the save handler. The Phase 5 flow (PATCH → `router.reload({ only: ["ui_preferences"] })` → `useThemeFromProps` watcher → DOM update) is the single canonical path; calling `applyTheme()` directly here would create a parallel update path and re-introduce the source-of-truth ambiguity Phase 5 is structured to prevent. The one exception is the reload-failure fallback documented in Phase 5's "Selector update algorithm" — that's the only sanctioned direct `applyTheme()` call after a save.
- **In `Login.vue`**: call `applyTheme('strategic')` on mount as a defensive guard — the SSR `data-theme` should already be `'strategic'`, but this closes the gap if a future code path ever renders login without `template_data`.

### Inertia prop access

Per-page application is error-prone if every authenticated page must remember to wire its own watcher. Centralize the behavior in a single composable used by every authenticated page:

**`useThemeFromProps()` composable** (one line per page).

Inertia prop typing — without an explicit type, `usePage().props.ui_preferences` is `unknown` and the composable will not pass `vue-tsc`. Two acceptable approaches:

- **Project-wide `PageProps` augmentation** (preferred, matches Inertia's documented pattern). The augmentation target is `@inertiajs/core`, NOT `@inertiajs/vue3`. Verified in the installed packages: `PageProps` is defined and exported from `node_modules/@inertiajs/core/types/types.d.ts:81`; `usePage<TPageProps extends PageProps = PageProps>()` in `node_modules/@inertiajs/vue3/types/app.d.ts:14` defaults to the core `PageProps`. Augmenting `@inertiajs/vue3` would miss the actual type definition and leave `unknown` in `vue-tsc`. Correct form, placed in `frontend/src/types/index.ts`:
  ```ts
  declare module "@inertiajs/core" {
    interface PageProps {
      ui_preferences?: UiPreferences
    }
  }
  ```
  One declaration, every `usePage()` call site benefits, no per-call-site generics.
- **Inline generic at the call site**: `usePage<{ ui_preferences?: UiPreferences }>()`. Less DRY but works as a fallback if the augmentation conflicts with something else. Same module-target rule does not apply — the inline generic bypasses augmentation entirely.

Use the augmentation. The composable then reads:

```ts
// frontend/src/composables/useThemeFromProps.ts
import { usePage } from "@inertiajs/vue3"
import { watch } from "vue"
import { applyTheme, isKnownTheme, normalizeTheme } from "../utils/theme"

export function useThemeFromProps() {
  const page = usePage()  // PageProps augmentation makes ui_preferences typed
  watch(
    () => page.props.ui_preferences?.theme,
    (raw) => {
      if (raw === undefined || raw === null) return  // preserve current DOM
      if (!isKnownTheme(raw)) return                  // preserve current DOM
      // First-tick note: with `immediate: true`, this fires on mount even
      // when SSR already set `<html data-theme="…">` to the correct value.
      // The resulting `applyTheme(...)` is an idempotent write to the same
      // value — intentional, not wasted work. Do NOT skip the first call
      // ("optimize away") on the grounds that SSR already did it; the
      // first call is what keeps the post-PATCH partial-reload path firing.
      //
      // SSR forward-compat note: this is safe under the current CSR-only
      // Inertia bootstrap. If SSR is ever introduced (createInertiaApp
      // with an SSR entrypoint), revisit — running this watcher during
      // hydration could fight Vue's SSR reconciliation if it mutates the
      // DOM before hydration completes. Likely fix at that point: gate
      // the first-tick call behind a "post-hydration" check via
      // onMounted() or a Vue isHydrated flag. Not needed for v1.
      applyTheme(normalizeTheme(raw))
      // normalizeTheme(raw) here is defensive symmetry, not strictly
      // required: after the isKnownTheme(raw) guard above, TypeScript has
      // narrowed `raw` to ThemeId and normalizeTheme returns it unchanged.
      // The normalizer IS load-bearing on two other paths and must stay
      // wherever those run: (1) the PATCH success → reload-failure fallback
      // (`applyTheme(normalizeTheme(savedThemeId))`) where the saved id
      // came from a server response and might in principle be anything,
      // and (2) the app-boot DOM read where dataset.theme is a raw string.
      // If you "optimize" this call to bare `applyTheme(raw)`, fine —
      // but do NOT generalize the optimization to those other sites.
    },
    { immediate: true }
  )
}
```

Every authenticated page calls `useThemeFromProps()` in `setup()`:

- `Schedule.vue`
- `Settings.vue`
- `Analytics.vue`

Behavior contract:

- When `ui_preferences.theme` is present and valid: apply it via `applyTheme(normalizeTheme(...))`.
- When `ui_preferences` is absent or its `theme` value is unrecognized (e.g. a partial Inertia reload that omits the prop, or an unexpected backend omission): the composable **does not call `applyTheme`**. The current `document.documentElement.dataset.theme` is preserved. Calling `applyTheme(normalizeTheme(undefined))` here would write `'classic'` and mid-session-reset a Strategic user's theme on every partial reload that omits the prop. The only time to fall back to `'classic'` via the DOM is at boot, when the DOM attribute itself is absent or unrecognized (covered in the boot algorithm above).

**Rule for new authenticated pages** (add to RULES.md as part of this feature): any new authenticated Inertia page MUST (a) be backed by a Django view that passes `ui_preferences` props AND `template_data={"initial_theme": ...}`, AND (b) call `useThemeFromProps()` in its setup block. The P7 "every authenticated Inertia HTML response includes an explicit `data-theme`" test enforces (a) automatically; the convention for (b) is enforced by the composable being the single supported entry point — no scattered `applyTheme()` calls in page components.

## Phase 4 - CSS token system

Files:

- Modify `frontend/src/app.css`
- Modify scoped styles in high-impact pages/components

### Global tokens

Introduce CSS variables in `frontend/src/app.css` under:

- `:root`
- `html[data-theme="classic"]`
- `html[data-theme="strategic"]`
- `html[data-theme="light_premium"]`

Token groups:

- page background;
- panel/card background;
- elevated surface background;
- primary text;
- muted text;
- faint text;
- border;
- strong border;
- primary accent;
- primary accent hover;
- primary accent contrast;
- danger surface/text/border;
- success surface/text/border;
- warning surface/text/border if needed;
- focus ring;
- shadow;
- radius;
- font family body;
- font family display;
- schedule block background;
- schedule gap background;
- chat/sidebar background;
- input background.

### Theme definitions

`Classic`:

- Match the current light neutral UI as closely as possible.
- Existing colors like `#f5f5f5`, `#ffffff`, `#111827`, `#6b7280`, `#3b82f6` become token values.

`Strategic`:

- Dark smoky background.
- Use generated CSS gradients/noise-like overlays in `app.css`, not external image assets. Prefer an inline SVG `feTurbulence` filter over a base64 PNG so the noise scales without resampling and stays under ~2KB.
- Serif display headings. The web-safe stack (`Georgia, "Times New Roman", serif`) ships first to keep v1 dependency-free, but it will not get within shouting distance of the strategicboard.ru editorial feel — that is the *single most distinctive* signal of the Strategic theme, and Georgia under-delivers it. **Hard deadline: lock this decision before Phase 4 token work begins** (i.e. before any `--font-family-display` / `--font-family-body` CSS variable is named or written). Reason: token names, font-family CSS variables, and the manual contrast audit all depend on whether headings are Georgia or a self-hosted face. Deferring the call into Phase 4 means a re-pass through every themed component if you swap families later. Two paths:
  - **v1 path (default)**: ship Georgia, accept the gap, document a v1.1 follow-up to swap in a self-hosted variable serif.
  - **v1+ path (recommended if Strategic feel is the headline win)**: pre-approve one self-hosted OFL variable serif (Fraunces, Playfair Display, or Source Serif 4), subset to Latin + Cyrillic, woff2, ~50–80KB. No external CDN — file lives in the repo and is served by Vite/WhiteNoise. **Constraint tie-break**: the "Open technical constraints" rule "avoid external fonts unless system stacks fail" refers to external/CDN-hosted fonts (Google Fonts, Adobe Fonts, third-party hosts). A self-hosted font file committed to the repo and served by the same origin as the app is explicitly allowed under this constraint — there is no external network dependency at runtime, no third-party tracking surface, no CDN outage risk. Implementers should not stall between the "Strategic needs a real serif" recommendation and the "avoid external fonts" constraint; the answer is "self-hosted yes, CDN no."
- Panels use translucent dark surfaces with low-opacity borders.
- Primary accent is a muted luminous blue.
- Preserve contrast for schedule text, buttons, form inputs, and chat messages.

`Light Premium`:

- Light warm or porcelain background.
- Slightly editorial serif headings.
- Refined borders and softer shadows.
- Same layout density as Classic unless a tokenized spacing change is safe.

### Theming conversion checklist (shared between P4 and P6)

Phase 4 (tokens) and Phase 6 (page/component theming) both sweep largely the same files. To avoid two parallel progress lists drifting apart, both phases reference this single checklist. Track progress here, not in either phase's prose. P4 owns "tokens defined and applied where the file lives"; P6 owns "page-level integration verified end-to-end" — same files, two passes, one list:

1. `frontend/src/app.css`: global page/body tokens.
2. Page shells:
   - `Schedule.vue`
   - `Settings.vue`
   - `Analytics.vue`
   - `Login.vue`
3. Shared navigation and cards:
   - `DateNavigator.vue`
   - `TimeBlock.vue`
   - `GapSlot.vue`
   - `AddBlockForm.vue`
4. AI surfaces:
   - `CommandBar.vue`
   - `ChatSidebar.vue`
5. Analytics/settings cards:
   - `CompletionBar.vue`
   - `CategoryBreakdown.vue`
   - `SkippedTasks.vue`
   - `TemplateEditor.vue`
   - `RulesList.vue`
6. Badges/toasts/buttons:
   - `DraftBadge.vue`
   - `RegenerateDraftButton.vue`
   - `UndoToast.vue`

Order matters: do them top-to-bottom so the app remains coherent after each step (global tokens land before page shells, page shells before deep components, etc.). The Phase 6 file list below is the same set — do not maintain it separately; update only this checklist when files are added or removed.

**Token-name freeze at end of Phase 4.** Once P4 closes, the CSS variable names (`--bg-page`, `--bg-panel`, `--font-family-display`, `--cat-focus`, etc.) are frozen. Phase 6 may add new tokens if a previously-unconsidered surface needs one, but must NOT rename existing tokens — every P4 file would have to be revisited and every test pinned to a token name would break. If P6 discovers a token should have been named differently, file a follow-up to rename in v1.1 across both phases atomically; do not do it mid-feature.

Do not attempt to eliminate every literal color in one pass. Prioritize visible surfaces and interaction states. Category colors may stay in `categoryColors.ts` for v1 because they encode semantic categories, not theme chrome.

### Category color contrast audit (mandatory before Strategic ships)

The current `categoryColors.ts` palette is tuned for a light Classic background. Several pastel values will lose perceptibility against the Strategic dark panel token. The audit must use the right WCAG target for the right usage — applying 4.5:1 (1.4.3 normal-text) to colors that don't sit behind text would force unnecessary overrides; applying nothing to colors that ARE text would let real failures through.

Per-usage breakdown (current as of plan time — re-verify before starting P4):

| Usage | File | WCAG target | Reference surface |
|---|---|---|---|
| Left border on a time block | `TimeBlock.vue` (`borderLeftColor`) | **1.4.11 (3:1) — UI component** | adjacent block background (`--bg-panel` or `--bg-elevated`) |
| Solid swatch dot in legend | `CategoryBreakdown.vue` (`background` of `.swatch`) | **1.4.11 (3:1)** | panel background behind the legend |
| Fill bar (20% alpha — `${color}33`) | `CategoryBreakdown.vue` fill bar | **Decorative — exempt from 3:1 requirement** (see note below) | n/a |
| Solid fill bar | `CategoryBreakdown.vue` second fill | **1.4.11 (3:1)** | bar track background |
| Dot marker on skipped task row | `SkippedTasks.vue` (`background`) | **1.4.11 (3:1)** | row/panel background behind the marker |
| Text contrast against a category-colored surface | — none today — | n/a | n/a |

**Translucent fill bar is decorative and exempt from 1.4.11.** A 20%-alpha category color blended over any track background produces a composite luminance nearly identical to the track — the resulting contrast against the track is always well below 3:1 regardless of the source color. For example, pure white at 20% over a near-black Strategic track yields approximately #333, which barely clears 3:1 even in the best case; with any pastel hue the composite is closer to 1.1:1. Meeting 3:1 would require ≥50% alpha in most themes, which defeats the visual intent of the "planned extent" indicator. The correct classification: the translucent fill is **decorative** under WCAG 2.1 Success Criterion 1.4.11 (non-text contrast applies only to "required for understanding" components — decorative elements are exempt). The solid inner bar (`bar-completed`) conveys the meaningful data and must meet 3:1. The translucent outer shell provides visual context and is exempt. Do not attempt to force 3:1 on the translucent fill by raising alpha; that requires an `getCategoryColor` alpha override per-theme with no guaranteed solution and breaks the visual hierarchy.

The 1.4.3 (4.5:1 text) check is **not required for v1** because no UI element renders text on top of a category-colored surface. If a future change adds such a surface (e.g. a colored chip with a label), reopen this audit.

Procedure:

1. For each of the three themes, render every (usage, category) pair against its actual reference surface — not a generic `--bg-panel` swatch. The 20%-alpha fill bar in particular is meaningless when measured against the panel; measure it against the bar's track.
2. Compute the contrast ratio for each pair. Use the WCAG-relative-luminance formula (any standard tool — axe DevTools, Stark, or a small script over the resolved CSS).
3. Any pair that fails its target gets a per-theme hex override. **The override value must be a hex color string, never a CSS `var()` reference.** `CategoryBreakdown.vue` produces a 20%-alpha tint via `` `${categoryColors[row.key]}33` `` ([CategoryBreakdown.vue:82](frontend/src/components/CategoryBreakdown.vue#L82)) — hex-string concatenation that silently produces invalid CSS if the value is `var(--cat-focus)`. Two implementation paths for the getter:
   - **Hex-only getter (recommended for v1)**: returns the per-theme hex override if one exists, otherwise falls back to the base hex in `categoryColors.ts`. The `${hex}33` pattern keeps working unchanged at all call sites.
   - **`getCategoryColor(category, { alpha? })` helper**: returns a solid hex by default, or `rgba(r, g, b, alpha)` computed from the hex when `alpha` is supplied. CategoryBreakdown's tint usage becomes `getCategoryColor(row.key, { alpha: 0.2 })`, eliminating the `33` suffix. Requires updating three call sites at [CategoryBreakdown.vue:74-89](frontend/src/components/CategoryBreakdown.vue#L74-L89), but expresses intent more clearly.
   
   Either path is acceptable. The invariant: stored values (base and override) must always be hex so alpha math can be applied safely at call time. CSS variables are not storable as category color values.
4. Document the audit results table in the PR description so reviewers can see which (usage, category, theme) cells needed overrides and which passed cleanly.

Exit criterion: zero (usage, category, theme) cells fail their target. Do not defer to v1.1 — a Strategic user staring at a washed-out "deep work" left border on every schedule is the kind of paper-cut that erodes confidence in the whole feature.

## Phase 5 - Settings theme selector

Files:

- Modify `frontend/src/pages/Settings.vue`
- Create `frontend/src/composables/usePreferences.ts` if the API logic is more than a few lines
- (No `useHttp.ts` change required — see "HTTP helper change" below for the rationale.)
- Add/update frontend tests

### Pre-Phase-5 spike: confirm `router.reload({ only: [...] })` semantics

**This spike is a blocking gate.** Do not open or merge the selector PR until the spike output is captured in the PR description and both behaviors below are confirmed to match what the plan assumes. The whole "PATCH → reload only → watcher updates DOM" flow rests on these two assumptions; if either differs in the installed versions, every test in the selector PR was written against the wrong contract.

Run a small spike against the actual installed `@inertiajs/vue3` + `inertia-django==1.2.0` versions to confirm two assumptions the plan rests on:

1. **`only: ["ui_preferences"]` refetches the named prop**: issue a `router.reload({ only: ["ui_preferences"] })` from a test page, confirm the server sees the request with the `X-Inertia-Partial-Data` header, and `inertia-django` serializes only the `ui_preferences` prop in the JSON response (not the full page prop tree). If it returns the full tree, the optimization is moot but the contract still works; the spike is to know which case you're in so prop-watcher tests can be written correctly.
2. **Missing `ui_preferences` in a partial-reload response preserves the DOM**: drive a partial reload that omits `ui_preferences` from the response (e.g. mock or force a server-side skip), observe that the `useThemeFromProps` watcher does NOT fire `applyTheme()` and `<html data-theme>` stays at its current value. The plan elsewhere asserts this; the spike validates it against the actual Inertia client behavior, not just the inferred behavior from reading the docs.
3. **`watch(..., { immediate: true })` first-tick timing vs first-navigation prop merge**: confirm the immediate watcher fires AFTER Inertia has merged shared/initial props into `page.props`, not before. Vue 3.5+ and Inertia minor releases have historically changed prop-merge timing around `createInertiaApp`'s `setup()` callback; if the watcher fires before the merge completes, `page.props.ui_preferences` would be transiently `undefined` at first tick and the watcher would (correctly per the absent-prop rule) skip the apply — but the SSR `data-theme` would already be right, so behavior is still correct. The spike's job here is to capture which sequence actually occurs so the test mocking strategy matches reality, not to fix anything (the design is robust to either ordering).

Output of the spike: a one-paragraph note in the implementation PR description confirming both behaviors with the actual installed versions. If either differs from the assumption, the plan needs an update before Phase 5 ships — flag back here rather than working around it silently.

### HTTP helper change (NOT required)

Earlier drafts of this plan proposed extending `requestJson` to accept an `AbortSignal` so the theme PATCH could be cancelled on navigation-away. That is removed. Aborting a mutating request via `AbortController` is unsafe: `abort()` cancels the client fetch but does not guarantee the server didn't process and commit the mutation. If the user clicks Strategic and immediately navigates away, the server may still commit `theme=strategic` to the DB while the abandoned tab keeps the old DOM theme — a silent divergence between server state and what the user last saw.

For v1 the theme PATCH is **not** cancelled on navigation-away. Two reasons it's a non-issue:

1. All three options are already disabled during save (per the selector spec above), so there is at most one in-flight PATCH per tab.
2. If the user navigates before the response arrives, the next page render reads fresh `ui_preferences` props from the server and applies the truthful DB state. There is no possible UI divergence after the next navigation.

The cost is one orphaned fetch promise per navigation-during-save, which the browser cleans up at unload. Acceptable trade-off vs. introducing a client-server consistency hazard.

`requestJson` keeps its existing 3-arg signature unchanged.

### UI placement

Add a new `Design` section in Settings above or below `Templates`. The page currently has `Templates` and `Rules`; placing `Design` first makes sense because it affects the entire app rather than scheduling content.

Selector shape:

- Three selectable cards (each rendering the registry preview tokens — see Phase 3) for `Classic`, `Strategic`, and `Light Premium`.
- Each card shows: theme name, one-line description, and a mini preview composed from `bgPage` / `bgPanel` / `accent` / `textPrimary` plus a sample heading in the theme's display font.
- Show current selection with a visible checked state — not color-only (a checkmark icon or `aria-checked` border treatment, so colorblind users and screen readers both perceive it).
- On click, PATCH the backend preference.
- During save: disable **all three** options and show a spinner on the just-clicked one. Do not leave siblings enabled. A second PATCH while one is in-flight produces a DB write-ordering race that the client-side stale-response guard cannot close: if PATCH A reaches the server after PATCH B, the DB commits A while the client shows B — silent data divergence. For v1, serializing writes by making the UI non-interactive during save is the correct fix. After save completes (success or failure), re-enable all options. This also eliminates the requestSeq/latestSeq complexity — there is only ever one in-flight PATCH at a time.
- **On success: do NOT call `applyTheme()` directly. Do NOT mutate a parallel local state ref.** The save flow is: PATCH succeeds → `router.reload({ only: ["ui_preferences"] })` → `useThemeFromProps`'s watcher fires on the new prop → DOM updates. One mechanism, one source of truth. See "Selector update algorithm" below for the full step list and the reload-failure fallback (the only sanctioned divergence from this rule).

**Cross-tab scope (accepted limitation for v1)**: the "disable all three during save" rule serializes PATCHes **within one tab only**. Two tabs of the same user can each PATCH a different theme concurrently — both succeed at the server (last write wins in the DB), but the loser tab's local `page.props.ui_preferences` and DOM stay on its own choice until that tab's next navigation or reload. Scope statement: **serialized per tab; cross-tab last-write-wins is accepted**. Justification: theme switching is a low-frequency action (a handful of times per user per lifetime), users rarely have Settings open in two tabs simultaneously, and the loser tab self-heals on its next page load. A v1.1 path exists if needed — a `BroadcastChannel("ui_preferences")` listener in `useThemeFromProps` would let one tab's successful PATCH push the new value to every other tab in the same browser session, triggering the watcher and converging the UIs without a navigation. Don't ship this in v1; it's complexity without a demonstrated need.
- On failure: leave the previous theme active and show a compact error message via `aria-live`. (Success behavior is intentionally not listed here — see the "do NOT call `applyTheme()` directly" bullet above and the "Selector update algorithm" subsection below.)

Accessibility requirements (must ship in v1, not as a follow-up):

- The three cards form a single radio group: `role="radiogroup"`, `aria-labelledby` pointing to the section heading.
- Each card is `role="radio"` with `aria-checked="true|false"`.
- Arrow keys move focus between options; `Space`/`Enter` selects.
- Focus-visible outline must be tested in all three themes — the default browser outline vanishes against Strategic's dark blue. Use a tokenized `--focus-ring` that is high-contrast in each theme.
- Error messages are surfaced via `aria-live="polite"`, not color-only.

**Disabled-state semantics (custom radios, not native inputs)**: the `disabled` HTML attribute has no effect on a `div` with `role="radio"`. The "disable all three during save" requirement must be implemented as:

- Set `aria-disabled="true"` on all three cards while the PATCH is in flight. Remove on completion (success or failure).
- The click handler must early-return when `aria-disabled === "true"`; the `keydown` handler must do the same on `Space`/`Enter`. Do not rely on visual disabled styling alone — keyboard users would otherwise still trigger the save.
- Keep all three cards focusable during save (do not remove from the tab order, do not set `tabindex="-1"`). Users may still want to navigate between options visually to compare; they just can't commit a change until save settles. ARIA convention is that `aria-disabled` elements remain focusable; `disabled` attribute on native inputs removes from tab order. We're matching the ARIA convention here, not the native convention.
- Apply a tokenized "disabled" visual treatment (reduced contrast, no hover affordance) that is distinguishable from the active state in all three themes.

Tests required for the disabled state:

- `aria-disabled="true"` is set on all three cards immediately after click and before the PATCH resolves.
- Clicking a sibling option while `aria-disabled="true"` does **not** trigger another PATCH (no second network request fires).
- Pressing `Space` or `Enter` on a focused card while `aria-disabled="true"` does **not** trigger another PATCH.
- `aria-disabled` is removed on both success and failure response paths.

### Selector update algorithm

All three options are disabled on click, so there is at most one in-flight PATCH at a time. No requestSeq or stale-response logic is required.

Concrete steps:

1. User clicks a theme option.
2. If it is already active, do nothing.
3. Disable all three options; show a spinner on the clicked one.
4. Send `PATCH /api/user/preferences/` with the selected theme id. No `AbortController` — see "HTTP helper change" above for why aborting a mutating request is unsafe.
5. On PATCH response:
   - On PATCH success: do **not** call `applyTheme()` directly. Issue `router.reload({ only: ["ui_preferences"], onSuccess, onError, onFinish })` (see callback contract below) and let the resulting prop change drive the DOM update through `useThemeFromProps`'s watcher. One mechanism, one source of truth, no race window.
   - On PATCH failure: show the backend error or a generic failure; keep the previous theme selected. No reload needed because nothing changed server-side. Re-enable all three options here (remove `aria-disabled`) — there is no subsequent async step.
6. **Reload callback contract.** `router.reload()` returns `void`, not a Promise — its async surface is the `onSuccess` / `onError` / `onFinish` callbacks. Do not `await` the call; do not run post-reload logic synchronously after the call returns.
   - `onSuccess`: the prop has refreshed; `useThemeFromProps`'s watcher has fired and updated the DOM. Selector's "active" indicator (sourced from `page.props.ui_preferences.theme`) and the `<html data-theme>` attribute update atomically. No additional work needed here.
   - `onError`: rare — network drop between PATCH-success and reload, or a transient server error on the prop refetch. The DB has the new value, but the local prop is stale. Fall back to applying the new theme manually via `applyTheme(normalizeTheme(savedThemeId))` AND surface a non-blocking warning ("Theme saved; refresh to sync"). Do not silently swallow the reload failure — the user needs to know their selector may be stale until they navigate.
   - `onFinish`: fires after both success and error paths. Re-enable all three options here (remove `aria-disabled`). Putting the re-enable in `onFinish` (and not in `onSuccess` plus duplicated in `onError`) guarantees the disabled state lifts exactly once, regardless of which terminal path the reload took.

**Source-of-truth rule**: the selector's "which option is checked" state reads exclusively from `page.props.ui_preferences.theme`. There is no parallel local `uiPreferences` ref that the component mutates independently. The single canonical update path is: PATCH → reload props → watcher fires → DOM and selector update together. The DOM-update-via-`applyTheme` fallback in the reload-failure case is the **only** sanctioned divergence from this rule, and it explicitly notifies the user.

If a future need arises to avoid the round-trip (e.g. perceived latency on slow networks), the alternative is to mutate `page.props.ui_preferences.theme` directly via Inertia's prop mutation mechanics so the watcher still fires — NOT to introduce a parallel local state ref. Document any such optimization in this section; do not add it silently.

If the user navigates away while the PATCH is in flight, the promise becomes orphaned and any error is suppressed by the unmounted-component guard (Vue throws if you mutate refs on a destroyed component — wrap the response handler in an `isMounted` check or use `onBeforeUnmount` to flip a flag). The server still commits the write; the next page render reflects the committed truth.

Avoid optimistic persistence for v1. Visual application happens only after the backend accepts the preference, so reload/login behavior cannot drift from what the user sees.

## Phase 6 - Page and component theming

Files: see the **Theming conversion checklist** in Phase 4 — Phase 6 operates on the same file set in the same order. Do not maintain a parallel file list here. Phase 6's responsibility is the page-level integration pass (interaction states, drag/ghost feedback, current-time line visibility, chat sidebar readability) over the same files that Phase 4 tokenized.

### Schedule page

The schedule is the primary product surface. The theme must preserve:

- time block readability;
- drag/ghost/shift visual feedback;
- current time line visibility;
- gap affordance;
- completed vs active block distinction;
- disabled state during draft generation;
- chat sidebar readability in wide layout.

Keep existing behavior and DOM test hooks stable. This feature should be visual unless a class is purely styling-related and has no test contract.

### Login page

`Login.vue` should statically apply `strategic` and use the new tokens. Since no user preference exists before auth, do not call the preferences API from login.

### Analytics page

Analytics panels should use tokenized card and text styles. Completion/success/error colors must remain semantically clear in all three themes.

### Settings page

Settings must be usable in all themes because it is where the user can recover from a theme they dislike. Ensure the selector, TemplateEditor, and RulesList remain readable in dark Strategic mode.

## Phase 7 - Tests and verification

Backend tests:

- Auth requirement for `GET /api/user/preferences/` and `PATCH /api/user/preferences/`.
- First `GET` creates or returns default `classic`.
- Valid `PATCH` changes the theme.
- Invalid theme returns 400 with a `theme` error.
- Invalid JSON returns 400 with a `body` error.
- Preferences are isolated per user.
- `settings_view`, `schedule_view`, and `analytics_view` include `ui_preferences` in their Inertia props.
- **Cache-Control contract**: every response from `GET /api/user/preferences/` and `PATCH /api/user/preferences/` includes `Cache-Control: private, no-store`. Test at least three response paths to exercise the response-helper enforcement: (a) `GET` success (200), (b) `PATCH` success (200), (c) `PATCH` invalid theme (400). The 400-path coverage is the load-bearing one — it catches a future implementer who adds a new error branch with a raw `JsonResponse(...)` instead of routing through the `_prefs_response` helper. Without an error-path assertion the test would pass while error responses leak across CDN/proxy boundaries.
- **Server-rendered first-paint contract — hard-load HTML, not Inertia partial reload.** The contract being verified is the SSR `template_data` wiring, which runs only on the hard-load path (no `X-Inertia` header — what a browser sends on a fresh navigation or hard refresh, returning full HTML with the Vue mount point). Inertia partial-reload requests return JSON with no HTML root element and are out of scope here. Two tests cover the contract:
  
  1. **Login**: a hard-load `GET reverse("login")` (resolves to `/accounts/login/` per [backend/day_forge/urls.py:13](backend/day_forge/urls.py#L13)) returns HTML with `<html ... data-theme="strategic">`. Login's value is hardcoded (no user preference exists pre-auth); test it on its own because the assertion target is a literal, not a function of state.
  
  2. **Authenticated pages — parametrized**: for each authenticated `inertia_render` call site (`schedule_view`, `settings_view`, `analytics_view`, and any future addition listed in the test), seed the test user with a non-default theme (e.g. `strategic`) so the fallback-vs-explicit distinction is observable, then issue a hard-load request and assert the response HTML contains `<html ... data-theme="strategic">` — equal to the *persisted* value, not just "present and valid." Per-page setup requirements:
     - `/schedule/<date>/`: use `timezone.localdate()` for the date to match the view's date validation.
     - `/settings/`: no extra setup.
     - `/analytics/<past-date>/`: seed a `Schedule` row at `today - timedelta(days=1)` plus at least one `TimeBlock`, because `analytics_view` returns 400 on future dates and 404 when no schedule exists ([backend/analytics/views.py:127-136](backend/analytics/views.py#L127-L136)).
  
  This parametrized test catches the two failure modes that ship the wrong theme silently: (a) an implementer wires the `ui_preferences` prop but forgets `template_data=` in `inertia_render` (the page falls back to the `'classic'` default in `base.html` and Strategic users see a flash), and (b) a future authenticated page is added without `template_data` and is not added to the test's page list — the rule "any new authenticated page must be in this list" is documented in RULES.md.
- **Concurrent first-visit race**: two concurrent first-GET requests for the same brand-new user must both succeed and result in exactly one `UserPreferences` row. Verifies the `get_or_create` requirement from Phase 1 isn't silently weakened to a fetch-then-insert. Implementation caveats:
  - Use `TransactionTestCase`, not `TestCase`. `TestCase` wraps each test in a transaction that's shared across the test's queries, so threaded queries inside one test would see one another's uncommitted state and the race wouldn't model production.
  - Each thread must open its own DB connection via `django.db.connection.ensure_connection()` (or `connections["default"].close()` + reopen at the top of the worker callable) — Django's connection is thread-local but a stale handle from the main test thread will leak in if you don't reset it.
  - **Do not share a Django test `Client` instance across threads.** Django's test client maintains per-instance session and cookie state that is not thread-safe; sharing one across workers produces session/cookie corruption that masquerades as `IntegrityError` or constraint-violation noise unrelated to `get_or_create`. Two acceptable patterns: (a) construct one `Client()` per worker and copy the authenticated session cookie into each before the worker fires its request; or (b) skip the client entirely and call the preference helper / view function directly inside the worker, since the contract under test is the model-layer `get_or_create` atomicity rather than the HTTP layer. Pattern (b) is simpler and equally informative.
  - SQLite serializes writes at the database level via its file lock, so the race may not reliably reproduce — concurrent INSERTs will queue rather than collide, and the `IntegrityError`-rescue branch of `get_or_create` may never actually fire under SQLite even when threads launch simultaneously. **Assert the end-state contract (exactly one `UserPreferences` row exists after both threads return) rather than instrumenting the `IntegrityError` code path.** End-state is the stable invariant across SQLite, Postgres, and any future backend; observable `IntegrityError` paths are an implementation detail of how the race resolves. On Postgres the race surfaces under genuine row-level lock contention and the rescue branch fires; on SQLite the writers queue and the second one sees the first's committed row via `get_or_create`'s `SELECT-after-failed-INSERT`. Both paths produce the same end state. Document the SQLite write-serialization in a test docstring; do not skip the test on SQLite (the `get_or_create` path is still exercised end-to-end, just not under contention).

Frontend tests:

- `normalizeTheme` maps invalid/missing values to `classic`.
- `applyTheme` sets `document.documentElement.dataset.theme` to the given id and performs no normalization.
- `useThemeFromProps` calls `applyTheme(normalizeTheme(...))` when `ui_preferences.theme` is present and valid.
- `useThemeFromProps` does **not** call `applyTheme` when `ui_preferences` is absent or `theme` is unrecognized (the DOM-preservation rule — failing this re-introduces the partial-reload theme-reset bug).
- **Every authenticated page actually calls `useThemeFromProps()`** — wiring contract. The composable being correct doesn't help if a page forgets to call it; partial-reload theme updates would silently break on that page even though SSR data-theme tests pass. Two acceptable implementations:
  - **Static scan test** (preferred, cheapest, catches the rule at source): a small Node test that reads each page file (`Schedule.vue`, `Settings.vue`, `Analytics.vue`, and any future page added to a list) and asserts the source contains `useThemeFromProps(`. One file IO + one regex per page. Add a comment in each page near the call so it survives an editor's "remove unused import" pass.
  - **Per-page mount test**: mock `useThemeFromProps`, mount each page, assert the mock was called once during setup. More faithful but ~10x heavier.
  Pick the static scan unless mount-based tests already exist for these pages. If a new authenticated page is added later, its file must be added to the scan's page list — that addition is part of the rule documented in RULES.md.
- `Settings.vue` renders the Design section with three options.
- Each option exposes `role="radio"` and `aria-checked` correctly.
- Arrow-key navigation moves focus across the radio group; `Space` selects.
- Selecting a different theme calls the preferences endpoint.
- Successful PATCH triggers `router.reload(...)` with the `ui_preferences` prop and all three callbacks wired. Assertion shape must use `expect.objectContaining` — exact-equality on the options object would either fail (because real callbacks are functions) or push the implementer to drop callbacks to make the test pass, defeating the contract:
  ```ts
  expect(routerReloadSpy).toHaveBeenCalledWith(expect.objectContaining({
    only: ["ui_preferences"],
    onSuccess: expect.any(Function),
    onError: expect.any(Function),
    onFinish: expect.any(Function),
  }))
  ```
  Then drive the branches by manually invoking the spy's captured callbacks: `routerReloadSpy.mock.calls[0][0].onSuccess()` to verify the success path, `.onError()` to drive the fallback, `.onFinish()` to verify re-enable.
- Reload `onError` path: the manually-invoked `onError()` callback triggers `applyTheme(normalizeTheme(savedThemeId))` AND surfaces a non-blocking warning via `aria-live`.
- Reload `onFinish` path: the manually-invoked `onFinish()` callback removes `aria-disabled` from all three options. Assert this fires in BOTH the `onSuccess`-then-`onFinish` and `onError`-then-`onFinish` sequences (Inertia guarantees `onFinish` runs after the terminal callback).
- Failed PATCH (the request itself, not the subsequent reload) keeps the previous theme active and surfaces an error via `aria-live`. No reload is issued.
- `Login.vue` applies `strategic`.

Playwright e2e (new script under `frontend/scripts/playwright/`):

- `theme-switch-persistence.mjs`: **preflight reset** (via `execSync` Django shell call — same pattern used by `ai-chat-*.mjs`) resets the `playwright` user's `UserPreferences.theme` to `classic` so the test starts from a known state regardless of prior runs → log in → visit `/settings/` → assert Classic is selected → click Strategic → wait for the PATCH to settle → assert `<html data-theme="strategic">` in the live DOM → reload → assert `<html data-theme="strategic">` in the DOM after page load → log out → assert `/accounts/login/` has `data-theme="strategic"` → log back in → assert Strategic is still selected → **postflight reset** (optional but courteous) resets preference back to `classic` so manual testers start fresh after the script runs.

**Scope of this test**: it verifies user-observable persistence — that the saved theme survives a reload and survives a log-out/log-in cycle. It does NOT prove server-rendered first paint (i.e. zero FOUC), because a post-reload DOM assertion runs after JS has settled and cannot distinguish "server sent the attribute" from "JS corrected it before Playwright measured." The server-render proof is covered by the backend Django tests (the "server-rendered first-paint contract" tests above), which use the raw Django test client with no JS runtime.

**Required JS-blocked FOUC check (separate Playwright script or a sub-step of the persistence script)**: this is mandatory, not optional, because the manual no-FOUC check above only works against a production build and the dev workflow needs an automated guard.

The test must **fail closed** — if the route interception misses, JS hydrates and `applyTheme()` silently corrects any wrong `data-theme`, producing a false pass. Dev mode serves the app entry at `http://localhost:5173/src/app.ts` ([base.html:10](backend/templates/base.html#L10)); production serves it at `/static/assets/app.js` ([base.html:13](backend/templates/base.html#L13)). The test must intercept **both** patterns and **assert that at least one app-entry request was actually aborted** before reading the DOM attribute:

```js
let abortedAppEntries = 0
await page.route("**/src/app.ts", (r) => { abortedAppEntries++; return r.abort() })
// Prod bundle filenames are hashed by Vite (e.g. `app-Xa9Bz12k.js`), so a
// literal `**/static/assets/app.js` glob WILL miss them. Two options:
//   (a) match the hashed pattern: `**/static/assets/app-*.js`
//   (b) read the Vite manifest at runtime to get the actual entry name
// (a) is enough for now; revisit if the manifest layout changes (e.g. if
// Vite ever moves entries out of `assets/`). The startup assertion below
// is the load-bearing guard — if neither pattern matches, the test fails
// closed with an explicit "did the bundle path change?" message rather
// than a misleading false pass.
await page.route("**/static/assets/app-*.js", (r) => { abortedAppEntries++; return r.abort() })
await page.goto("/settings/", { waitUntil: "domcontentloaded" })
if (abortedAppEntries === 0) throw new Error(
  "JS-blocked FOUC test wired wrong: no app-entry request was intercepted. " +
  "Did the bundle path change? Check Vite manifest output and update the route globs."
)
const theme = await page.locator("html").getAttribute("data-theme")
// assert theme === "strategic" (with Strategic seeded for the test user)
```

With Strategic saved for the test user, the assertion is `data-theme === 'strategic'` even with no JS executed — proving the value came from the server-rendered HTML, not from `applyTheme()`. Add this as a step in `theme-switch-persistence.mjs` or a sibling script `theme-no-fouc.mjs`; either works.

This script does not call the LLM and has no rate-limit interaction, so it can run in parallel with the existing `ai-*.mjs` scripts. Add it to the manual-testing doc per the same pattern used for the ai-chat scripts.

Manual checks:

- Start app and log in.
- Visit schedule, settings, and analytics in each theme.
- Switch from Classic to Strategic to Light Premium and reload after each switch.
- **No-FOUC check (production build only)**: this check is **not valid against the Vite dev server**. In dev, `base.html` loads CSS via the Vite JS module ([backend/templates/base.html:9-10](backend/templates/base.html#L9-L10)), not as a blocking `<link rel="stylesheet">`, so any flash on Slow 3G measures Vite's CSS-injection latency rather than the SSR-vs-JS theme mismatch this check exists to catch. Run `cd frontend && npm run build` first, then start Django with `DEBUG=0` so the production `<link>`-based CSS path is exercised. With Strategic saved, hard-reload Schedule under Slow 3G in dev tools — the page must render dark from the first paint with zero Classic-light flash. If a flash appears, the Phase 2 server-rendered `data-theme` step is missing or wired wrong. Because this manual check requires a production build, the **JS-blocked Playwright check (below) is mandatory, not optional** — it provides the automated guard for dev-mode iteration.
- Log out and confirm login remains Strategic.
- Log back in and confirm the saved user theme is restored.
- On the schedule page, verify drag, add block, edit title, completion toggle, delete, AI chat/sidebar, undo toast, and now-line remain readable.
- Tab through the Settings Design selector with the keyboard alone in each theme. Focus must be visible on every option in every theme.

Commands:

- Backend lint: `uv run ruff check backend/`
- Backend tests: `uv run pytest backend/tests/ -v`
- Frontend tests: `cd frontend && npm test`
- Frontend type check/build: `cd frontend && npx vue-tsc --noEmit` or `cd frontend && npm run build`

## Implementation workflow

This feature touches 40+ files across 7 phases. **Before starting implementation**, break the work into smaller tasks and track them in `tasks/todo.md` as checkable items. (The same convention is documented in `.claude/rules/code-style.md` for any change touching >3 files, but the requirement here is stated directly so the plan stands on its own regardless of which rule-doc location is canonical in a given session.)

**Pre-implementation inventory step (required)** — before opening Phase 1, run:

```bash
grep -rn "inertia_render\|inertia\.render\b" backend/ --include="*.py" | grep -v test | grep -v migrations
```

Cross-check the resulting call sites against the authenticated-page list in this plan (`settings_view`, `schedule_view`, `analytics_view`, plus `login_view`'s three render paths). Any call site not in the plan is either (a) a missed page that needs `ui_preferences` + `template_data` + `useThemeFromProps` wiring, or (b) a deliberate exemption that needs to be documented. As of plan time, the inventory matches exactly: 5 call sites total (1 + 1 + 1 + 3). If the grep returns more, update Phase 2 page-props list, Phase 3 page wiring list, and the P7 parametrized "every authenticated hard-load page" test before proceeding.

1. Create a `tasks/todo.md` section for feature 0010 with one checkable item per phase (P1–P7), plus items for the mandatory cross-phase prerequisites: `base.html` `data-theme` wiring with `template_data=` on every `inertia_render` call site (P2 prereq), `_render_login` helper that enforces Strategic on all three login render paths (P2 prereq), category color contrast audit (P4 exit gate), unmounted-component guard in the Settings selector PATCH handler (P5 prereq — replaces the dropped `requestJson` signal extension; see Phase 5 "HTTP helper change" for why aborting a mutating request is unsafe).
2. Check off each item as its phase is committed and verified.
3. If a phase is split across multiple PRs, create sub-items.

The plan is already phase-gated, so the todo list maps directly to the phases. Do not start P3 without P1 and P2 committed; do not start P5 without P4 exit criterion (contrast audit) passing.

## Open technical constraints

- Keep `categoryColors.ts` as the category swatch source for v1 unless theme contrast forces a small token bridge.
- Avoid external fonts and image assets in v1 unless local/system stacks fail the desired look.
- Avoid moving the app to Tailwind or adding a UI kit; current project uses Vue SFC scoped CSS and plain CSS.
- Do not rewrite layout architecture into a shared layout component unless implementation proves repeated theme application code becomes error-prone.
- Do not make theme choice local-only; the clarified requirement is backend profile persistence.
