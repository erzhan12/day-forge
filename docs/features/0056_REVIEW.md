# Feature 0056 — External review trail

Feature: Settings topic-based left navigation (issue #155).
Working tree on `main` (unstaged). Reviewer: OpenAI Codex (`gpt-5.6-sol`), read-only. Cursor agent not requested.

## External review loop (ext-code-review) — 3 iterations, SUCCESS

Engine: **codex only**.

### Iteration 1 — 1 P2 accepted & fixed

- **P2** `useSettingsTopic.ts` `scrollIntoView({ block: "start" })` hid the focused heading under the sticky mobile topic `<select>`. Added `.settings-topic-heading` with `scroll-margin-top: 6.5rem` (24px at ≥1024px) and a class assertion in `Settings.test.ts`.
- **P3 (fixed, cheap):** Playwright README claimed 22 scripts; on-disk scenarios are 19. `RULES.md` still said 21. Both updated to 19.
- **P3 ignored:** pointer/Tab-then-pointer tests incomplete; integration-form draft preservation unit-test-light; `TemplateEditor` `deleted` re-emission untested; Apple/Todoist/Habitica error/message/busy panel props untested.

### Iteration 2 — 1 P1 accepted & fixed

- **P1** `Settings.vue` bound `:inert="activeTopic !== '…'"`. Vue 3.5 emits `inert="false"` for the active panel; HTML treats the attribute’s *presence* as true, so every panel (including the visible one) was inert. Changed to `:inert="activeTopic === '…' ? undefined : true"`. Confirmed with a failing test (`inert="false"` on the active panel) then greened it.
- **P3 ignored:** `scrollIntoView` not spied in unit tests; OAuth `?google=connected` branch untested (error path covered); dense one-line watchers in `Settings.vue`.

### Iteration 3 — clean

- Codex: **NO P1/P2 FINDINGS**. Remaining P3s: `.subsection-title` 18px vs old 14px/600; scroll-margin class without a `scrollIntoView` spy.

## Accepted non-blocking gaps (P3)

- Subsection heading scale/weight in Integrations and Templates panels vs pre-refactor `Settings.vue`.
- Unit tests do not spy `scrollIntoView` or cover pointer-click / Tab-then-pointer focus, `?google=connected`, or Apple/Todoist/Habitica busy/error props.
- Integration-form draft preservation is e2e-conditional when connect forms are absent.

## Final verification

- Frontend: `npm test` — 894 passed. `vue-tsc --noEmit` clean. `ruff check backend/` clean.
- Result: **SUCCESS** — zero valid P1/P2, tests + lint green.
