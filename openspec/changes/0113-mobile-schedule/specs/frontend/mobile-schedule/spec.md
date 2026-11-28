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
At 640 px and below in Dark 4a the header SHALL be one 56 px row with previous, a centered `Fri, Nov 27` date, next and a gear that opens a menu of Settings, View analytics, Calendars and Log out. The header SHALL NOT show Undo, Show indicator, Today, Regenerate draft, the draft badge or the time-zone banner.

#### Scenario: Menu contents
- **WHEN** the gear is tapped
- **THEN** the menu lists Settings, View analytics, Calendars and Log out

### Requirement: Mobile edit sheet
Tapping a block row outside its checkbox, handle and × SHALL open a bottom sheet that edits the title only; time and category editing is out of scope (issue #333).

#### Scenario: Rename
- **WHEN** the row is tapped and a new title is saved
- **THEN** the block is renamed through the page writer and an Undo entry is registered
