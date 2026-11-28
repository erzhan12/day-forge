# 0113 — mobile schedule tasks

## 1. Scaffold (PR1)
- [x] `useIsMobile` and `MOBILE_VIEWPORT_QUERY` in `useViewport.ts`, with unit tests
- [x] Viewport meta with `viewport-fit=cover, interactive-widget=resizes-content`
- [x] Safe-area and `--app-height` variables; Dark 4a mobile background and `dvh` height
- [x] OpenSpec change, `0113_PLAN.md`, rules (`ui.md`, `ai-safety.md`)

## 2. Header and menu (PR2)
- [x] One-line 56 px header, 44 px targets, centered date (`MobileHeader`, `formatMobileHeaderDate`)
- [x] ⚙ menu: Settings, View analytics, Calendars, Log out (`MobileMenu`, `useMobileDialog`)
- [x] Hide Undo, Show indicator, Today, Regenerate draft, draft badge, time-zone banner on mobile
- [x] Calendars sheet (`MobileCalendarsSheet`); choice recorded in design.md

## 3. List (PR3)
- [ ] `TimelineMobile`, block row 52 px, free row 48 px, no axis or now line
- [ ] Completion via `useBlockCompletion`; × deletes without dialog
- [ ] Update `dark4a-day-fit.mjs` 390 px checks

## 4. Sheets and FAB (PR4)
- [ ] `BottomSheet`, Add Block sheet, title-only edit sheet (time and category: issue #333), FAB

## 5. Toast (PR5)
- [ ] Mobile Undo toast, 5 s, delete, move and add texts; add `Enforced:`/`Tests:` to the undo-and-drag delta

## 6. Chat (PR6)
- [ ] Rest and focus panel, `visualViewport` inset, ⓘ sheet, chips
- [ ] Update `ai-chat-privacy-hint-always-on.mjs`; add anchors to the chat-ui delta

## 7. Drag (deferred)
- [ ] Touch drag with 400 ms long press on the handle (not scheduled)

## 8. Close-out (PR8)
- [ ] `mobile-day-fit.mjs` at 390×844 and 375×667; `make e2e`
- [ ] Add anchors for the mobile-schedule layout requirements
- [ ] Run `make check`, `make spec-check` and `make frontend-build`
- [ ] Archive the change on the last feature branch before merge
