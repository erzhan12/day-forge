# 0105 — Sources rail redesign tasks

- [x] Tokens (`--provider-*`, `--checkbox-*`, `--calendar-hue-*`) and `.df-checkbox` in `app.css`
- [x] `calendarColor.ts`, `externalRailSectionsStorage.ts`, `formatShortCivilDate`, `tickVariantFor` with tests
- [x] Unified checkbox in `TimeBlock.vue`, `TimeBlock4a.vue`, `Schedule.vue` ghost block, Todoist and Habitica panels
- [x] Always-mounted `TransitionGroup` with leave animation in both task panels, with rollback tests
- [x] `RailSection.vue`; `ExternalRail4a.vue` rewrite (header, sections, `progress`, `calendarSummary`, `toggleSection`, tokens)
- [x] `ExternalEventsPanel` `embedded` mode
- [x] Update and extend `externalRail4a.test.ts`, `ExternalEventsPanel.test.ts`, panel tests
- [x] Fix the stale sidebar selector in `todoist-complete-refresh.mjs` and `todoist-integration.mjs`
- [x] Spec deltas with real test anchors; RULES.md note
- [x] Run `make check`
- [x] Run `make spec-check`
- [x] Run `make frontend-build`
- [x] Browser check on `dark_4a` (collapse, keyboard, persistence, checkboxes); light themes checked through resolved tokens only
- [x] Archive the change on the feature branch before merge
