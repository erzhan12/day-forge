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
At 640 px and below in Dark 4a the Schedule page SHALL render the day as one column of fixed-height rows in time order (block 52 px, free row 48 px, 8 px gap) with no hour axis and no now line, one free row per gap including the edge gaps, and no row for touching blocks.
Enforced: frontend/src/components/TimelineMobile.vue::timeline-mobile, frontend/src/utils/mobileRows.ts::buildMobileRows, frontend/src/pages/Schedule.vue::TimelineMobile

#### Scenario: Rows of the day
- **WHEN** a day has blocks with gaps before, between and after them
- **THEN** each block and each gap is one row, in order, and the trailing gap is not split at the clock

Tests: frontend/tests/MobileList.test.ts::buildMobileRows (feature 0113)::lists edge and inner gaps in time order and none between touching blocks, frontend/tests/MobileList.test.ts::buildMobileRows (feature 0113)::returns one whole free row for an empty day, frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::renders a block row per block and a free row per gap, with no axis or now line

#### Scenario: Only Dark 4a on a phone
- **WHEN** the theme is classic or the viewport is wider than 640 px
- **THEN** the existing timeline renders instead

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a mobile header (0113)::renders the phone list instead of the stacked timeline only in Dark 4a at 640px and below

#### Scenario: Short block
- **WHEN** a 5-minute block is on the day
- **THEN** it renders as a full 52 px row with start time, `5m` and × visible and no end time

Tests: frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::shows start time, duration and ×, and no end time, for a 5-minute block

### Requirement: Mobile free row
A free row SHALL show `Free · 1h 45m`, its range and a visible +, and tapping it SHALL offer the gap's 5-minute-grid range to the Add Block form; a gap with no 5-minute slot, or a disabled schedule, SHALL ignore the tap.
Enforced: frontend/src/components/MobileGapRow.vue::mobile-gap-row

#### Scenario: Label and tap
- **WHEN** a free row is tapped
- **THEN** it emits the snapped start and end, and tiny or disabled gaps emit nothing

Tests: frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::labels free rows with duration and range, frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::emits the grid-snapped range when a free row is tapped, and ignores tiny or disabled gaps

### Requirement: Mobile block row behavior
A mobile block row SHALL complete through the shared completion queue with the global `.df-checkbox`, delete on the × tap with no dialog and with an Undo entry, keep the title tap as inline rename, and show its grip as inert and hidden from assistive tech until touch drag exists.
Enforced: frontend/src/components/TimeBlock.vue::onDeleteClick, frontend/src/components/MobileBlockRow.vue::mobile-block-row

#### Scenario: Complete and rename
- **WHEN** the checkbox is toggled or the title tapped
- **THEN** the completion write goes through `updateBlock` and the title becomes an input

Tests: frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::completes through the shared completion queue, frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::keeps the inline title edit on a tap of the title

#### Scenario: Delete without a dialog
- **WHEN** × is tapped
- **THEN** the block is deleted at once and an Undo entry is pushed; a failure shows a floating alert

Tests: frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::deletes on the × tap without a confirmation dialog and registers Undo, frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::floats a delete failure instead of growing the 52 px row

#### Scenario: Inert grip
- **WHEN** the grip is pressed
- **THEN** no drag starts

Tests: frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::keeps the grip inert: no drag starts from it

### Requirement: Mobile FAB
At 640 px and below in Dark 4a the dashed Add Block bar SHALL be replaced by a 56 px coral FAB 16 px from the right and 16 px above the chat panel with the safe area, opening the same add form, hidden while the chat field is focused.

#### Scenario: FAB
- **WHEN** the mobile Schedule page renders
- **THEN** the FAB opens the add form and the bar is absent

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
