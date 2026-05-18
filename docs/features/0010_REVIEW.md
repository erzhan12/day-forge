---
name: "0010 design templates - implementation review"
description: Code review against docs/features/0010_design_templates_PLAN.md
date: 2026-05-18
---

# Feature 0010 - Code Review

## Findings

### Low - Preferences cache-header invariant is still not literal for 302/405

The plan required `Cache-Control: private, no-store` on every preferences response, explicitly including unauthenticated redirects and unsupported methods. The current implementation still documents and tests an intentional delta:

- `backend/templates_mgr/api.py:402-415`
- `backend/tests/test_user_preferences_api.py:113-150`
- `docs/api.md:412`

Decorator-generated `302` and `405` responses bypass `_prefs_response()`, and tests assert the header is absent. Practical risk remains low because those responses do not include preference JSON, but this is still a deviation from the written plan. Either keep it as an accepted, documented delta or add narrow middleware/wrapping and flip the tests to require `no-store` on those paths.

## Confirmed Good

- The draft-generation overlay fix holds: `Schedule.vue` uses a theme-aware `color-mix(...)` page wash and tokenized spinner track.
- The reviewed analytics badge fix holds: `.status-reviewed` uses `var(--success-surface)`, `var(--success-text)`, and `var(--success-border)` together.
- The active analytics badge fix holds: `.status-active` uses dedicated `--info-*` semantic tokens. `semanticContrast.test.ts` verifies success/danger/warning/info foreground-surface pairs at >= 4.5:1 across Classic, Strategic, and Light Premium.
- Backend preference storage and API are aligned with the plan: `UserPreferences.Theme`, one-to-one row, admin registration plus User inline, frozen DTO, read-side normalization without write-on-read, corruption-healing PATCH, same-value PATCH success, unknown-field semantics, and per-user isolation.
- Authenticated page props and SSR first-paint wiring are correct: Schedule, Settings, and Analytics pass `ui_preferences: { theme }` plus `template_data={"initial_theme": ...}`. Login render paths share the Strategic helper.
- Frontend theme application is structured correctly: app boot preserves SSR `data-theme`, authenticated pages call `useThemeFromProps()`, partial reloads without `ui_preferences` preserve the current DOM value, and Login defensively applies Strategic on mount.
- The Settings design selector follows the intended source-of-truth model and save flow: PATCH, `router.reload({ only: ["ui_preferences"] })`, watcher-driven DOM update, reload-failure fallback, unmount guards, serialized saves, and accessible custom-radio behavior.
- The earlier selector arrow-key and category-color reactivity issues remain fixed. `DesignSelector.test.ts` covers arrow movement while saving, and `themeReactivity.test.ts` covers `TimeBlock` / `SkippedTasks` color updates.

## Tests Reviewed

Backend coverage is strong for DTO behavior, normalization, PATCH happy/error paths, corruption healing, cache headers on in-view success/error paths, page props, SSR `data-theme`, per-user isolation, and the documented 302/405 header delta.

Frontend coverage includes theme utilities, prop watcher behavior, authenticated-page wiring, selector click/keyboard/disabled paths, reload callbacks, unmount guards, category color overrides/reactivity, accent contrast scanning, fixed-background/themed-foreground scanning, numeric semantic contrast checks, and existing Schedule/Analytics behavior.

Remaining risk is visual QA breadth rather than a known code defect: the automated tests cover the core token contrast contracts, but a rendered pass in Strategic and Light Premium is still useful before merging for spacing, focus rings, and translucency effects.

## Verification Run

- `uv run ruff check backend/` - passed.
- `uv run pytest backend/tests/test_user_preferences_api.py -q` - 34 passed, 29 warnings about missing `staticfiles/`.
- `cd frontend && npx vue-tsc --noEmit` - passed.
- `cd frontend && npm test -- DesignSelector theme useThemeFromProps themeWiring themeReactivity categoryColors accentContrast semanticContrast Analytics Schedule -- --run` - 12 files / 101 tests passed.
