## ADDED Requirements

### Requirement: Mobile breakpoint
The frontend SHALL expose `useIsMobile`, true when the viewport matches `(max-width: 640px)` and following changes, and the mobile layout SHALL apply only when that flag and the Dark 4a layout are both on. `useViewport` and its 1024 px `isWide` SHALL be unaffected.
Enforced: frontend/src/composables/useViewport.ts::useIsMobile

#### Scenario: Boundary at 640 px
- **WHEN** the viewport is 640 px wide, then 641 px
- **THEN** `isMobile` is true, then false

Tests: frontend/tests/useViewport.test.ts::useIsMobile (feature 0113)::treats 640px as inclusive and 641px as not mobile, frontend/tests/useViewport.test.ts::useIsMobile (feature 0113)::initial isMobile mirrors matches and follows change events

#### Scenario: Wide flag untouched
- **WHEN** `useViewport` is called
- **THEN** it queries only `(min-width: 1024px)` and registers its own listener

Tests: frontend/tests/useViewport.test.ts::useIsMobile (feature 0113)::leaves useViewport isWide on its own 1024px query

### Requirement: Mobile page shell
The page SHALL use `viewport-fit=cover` and `interactive-widget=resizes-content`, and at 640 px and below in Dark 4a SHALL size the shell with `100dvh` (100vh fallback) on the `#17181A` background. Other themes SHALL keep their appearance by padding the body with the system safe-area insets.
Enforced: backend/templates/base.html::viewport-fit=cover, frontend/src/app.css::--app-height

#### Scenario: Shell scaffold
- **WHEN** a phone with a notch opens any page
- **THEN** content stays inside the safe area and Dark 4a at 640 px and below fills `100dvh`

### Requirement: Mobile list layout
At 640 px and below in Dark 4a the Schedule page SHALL render one column of fixed-height rows (block 52 px, free row 48 px, 8 px gap) with no hour axis, no now line and no Add Block bar, and SHALL open Add Block from a 56 px FAB and from a free row.

#### Scenario: Short block
- **WHEN** a 5-minute block is on the day
- **THEN** it renders as a full 52 px row with its duration and × visible

### Requirement: Mobile header and menu
At 640 px and below in Dark 4a the header SHALL be one 56 px row: previous, a centered `Fri, Nov 27`, next, and a gear opening a modal menu (Settings, View analytics, Calendars, Log out). It SHALL NOT show Undo, Show indicator, Today, Regenerate draft, the draft badge or the time-zone banner.
Enforced: frontend/src/components/MobileHeader.vue::mobile-header, frontend/src/pages/Schedule.vue::mobileLayout

#### Scenario: Header contents
- **WHEN** the mobile Schedule page renders
- **THEN** it shows the short date and arrows, and none of the desktop-only controls

Tests: frontend/tests/MobileHeader.test.ts::MobileHeader (feature 0113)::shows the short date and nothing from the desktop header, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a mobile header (0113)::swaps the date navigator for the mobile header and drops the desktop-only controls, frontend/tests/date.test.ts::formatMobileHeaderDate (feature 0113)::formats %s as %s without year or full weekday

#### Scenario: Day arrows
- **WHEN** next or previous is tapped
- **THEN** the page visits the adjacent civil day

Tests: frontend/tests/MobileHeader.test.ts::MobileHeader (feature 0113)::moves one civil day with the arrows, across a month end

#### Scenario: Menu contents and logout
- **WHEN** the gear is tapped and Log out is chosen
- **THEN** the menu lists its items and the session ends through the page logout

Tests: frontend/tests/MobileHeader.test.ts::MobileHeader (feature 0113)::opens a menu with Settings, View analytics, Calendars and Log out, frontend/tests/MobileHeader.test.ts::MobileHeader (feature 0113)::omits View analytics and Calendars when they do not apply, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a mobile header (0113)::logs out from the menu

#### Scenario: Focus and dismissal
- **WHEN** the menu opens, Tab is pressed at its ends, then Escape
- **THEN** focus moves in, wraps inside the menu, and returns to the gear on close

Tests: frontend/tests/MobileHeader.test.ts::MobileHeader (feature 0113)::moves focus into the menu, wraps Tab, and closes on Escape with focus back on the gear, frontend/tests/MobileHeader.test.ts::MobileHeader (feature 0113)::closes on a backdrop tap

#### Scenario: Other layouts unchanged
- **WHEN** the theme is classic or the viewport is wider than 640 px
- **THEN** the desktop date navigator and its controls render

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a mobile header (0113)::keeps the desktop header in classic and in Dark 4a above 640px

### Requirement: Mobile Calendars sheet
On mobile the calendar panel SHALL not render under the timeline; the Calendars menu item SHALL open it in a modal sheet whose Add to schedule closes the sheet, and calendar polling SHALL stay as at widths below 1024 px.
Enforced: frontend/src/components/MobileCalendarsSheet.vue::useMobileDialog, frontend/src/pages/Schedule.vue::mobileCalendarsOpen

#### Scenario: Open and close
- **WHEN** Calendars is chosen and then Escape pressed
- **THEN** the panel shows inside the sheet, polling stays active, and focus returns to the gear

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a mobile header (0113)::moves the calendar panel into the gear menu's Calendars sheet and keeps polling

### Requirement: Mobile edit sheet
Tapping a block row outside its checkbox, handle and × SHALL open a bottom sheet that edits the title only; time and category editing is out of scope (issue #333).

#### Scenario: Rename
- **WHEN** the row is tapped and a new title is saved
- **THEN** the block is renamed through the page writer and an Undo entry is registered
