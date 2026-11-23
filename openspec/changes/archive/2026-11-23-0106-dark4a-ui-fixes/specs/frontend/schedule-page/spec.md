## ADDED Requirements

### Requirement: Dark 4a stack layout
The Dark 4a timeline SHALL stack its items without overlaps or holes, render each block at least 28 px tall and each free gap at most the edge-stub height, merge time-contiguous free gaps, and place hour labels and the now line through the same axis map. Other layouts SHALL keep the linear scale.
Enforced: frontend/src/utils/timelineStack.ts::buildTimelineStack, frontend/src/composables/useTimelinePresentation.ts::createTimelinePresentation

#### Scenario: Short block and long gap
- **WHEN** a day has a 5-minute block and a 170-minute free gap
- **THEN** the block renders 28 px tall, the gap 60 px, and every later item moves down accordingly

Tests: frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::heights::raises a 5-minute block to 28px, frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::heights::caps a 170-minute gap at 60px, frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::stacking::stacks items with no overlap and no hole

#### Scenario: Clock moves through the day
- **WHEN** the current time falls inside a capped gap or moves past the last block
- **THEN** the now line sits proportionally inside that row and the column height does not change

Tests: frontend/tests/timelinePresentation.test.ts::timeline presentation in stack mode (0106)::places the now line inside a capped gap proportionally, frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::linear equivalence and fixture::keeps the fixture at 538px at any clock time

#### Scenario: Classic layout
- **WHEN** the theme is not Dark 4a
- **THEN** the timeline keeps its linear geometry

Tests: frontend/tests/timelinePresentation.test.ts::timeline presentation in stack mode (0106)::linear mode is unchanged

### Requirement: Dark 4a compact block row
A Dark 4a block rendered below 36 px SHALL show one line with the checkbox, start time, duration, title and delete control, and SHALL offer its full title, time range and category in a tooltip on hover, focus or long press; a long press SHALL NOT open the title editor.
Enforced: frontend/src/components/TimeBlock.vue::showTooltip, frontend/src/utils/timelineStack.ts::COMPACT_BELOW_PX

#### Scenario: Compact row content
- **WHEN** a 5-minute block renders in Dark 4a
- **THEN** it shows the start time and duration without the end time and keeps the delete button

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock compact density and tooltip (0106)::compact density shows start time and duration without the end time, frontend/tests/TimeBlock.test.ts::TimeBlock compact density and tooltip (0106)::keeps start time, duration and × on a compact current block

#### Scenario: Tooltip and long press
- **WHEN** the user hovers, focuses or long-presses a compact block
- **THEN** the tooltip lists the title, range with duration and category, and a long press does not start editing

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock compact density and tooltip (0106)::tooltip lists title, 11:40–11:45 · 5m and category, frontend/tests/TimeBlock.test.ts::TimeBlock compact density and tooltip (0106)::a long press shows the tooltip and does not start editing, frontend/tests/TimeBlock.test.ts::TimeBlock compact density and tooltip (0106)::a cancelled long press shows no tooltip and a tap still edits

### Requirement: Dark 4a gap row
A Dark 4a free gap SHALL read `Free · <duration>` with its range and a visible add affordance, and activating it SHALL open the Add Block form with the gap's 5-minute-grid range, also after a Cancel; a gap without a 5-minute slot SHALL be inert.
Enforced: frontend/src/components/GapSlot4a.vue::activate, frontend/src/components/AddBlockForm.vue::addRequestId

#### Scenario: Label and add
- **WHEN** the user activates a 170-minute gap row
- **THEN** it reads `Free · 2h 50m` and `12:10–15:00` and emits the snapped range

Tests: frontend/tests/GapSlot4a.test.ts::GapSlot4a (0106)::shows Free · 2h 50m and 12:10–15:00 on a capped row, frontend/tests/GapSlot4a.test.ts::GapSlot4a (0106)::emits the grid-snapped gap range on click and on Enter, frontend/tests/GapSlot4a.test.ts::GapSlot4a (0106)::is inert when the gap has no 5-minute slot

#### Scenario: Reopen after Cancel
- **WHEN** the same gap is activated again after Cancel
- **THEN** the form opens again in Dark 4a and the classic handler keeps today's behaviour

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a gap add (0106)::reopens the form when the same gap is activated after Cancel, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a gap add (0106)::keeps the classic gap handler unchanged

### Requirement: Dark 4a empty day without a template
On a Dark 4a day with no slot template, no blocks and no draft generating, the page SHALL show an empty state naming the weekday, linking to the templates settings and offering Plan with AI, which focuses the chat input or, when that input is disabled, the chat status; the header SHALL omit the missing-template warning.
Enforced: frontend/src/components/EmptyDayState.vue::copy, frontend/src/utils/emptyDayCopy.ts::emptyDayCopy, frontend/src/components/CommandBar.vue::honourFocusRequest

#### Scenario: No template
- **WHEN** a Dark 4a Sunday has no weekend template and no blocks
- **THEN** the page shows `No template for Sunday` instead of the timeline and the header shows no warning

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a empty day and header (0106)::shows the empty state instead of the timeline on a 4a day with no template and no blocks, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a empty day and header (0106)::hides the header warning in 4a and keeps it in classic, frontend/tests/emptyDayCopy.test.ts::emptyDayCopy (0106)::names the weekday of the selected date in English

#### Scenario: Plan with AI
- **WHEN** the user activates Plan with AI
- **THEN** the chat input receives focus in the sidebar or the dock, or the chat status does when the input is disabled

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a empty day and header (0106)::Plan with AI focuses the chat textarea with a collapsed wide sidebar, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a empty day and header (0106)::Plan with AI focuses the dock below 1024px, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a empty day and header (0106)::Plan with AI focuses the chat status when the input is disabled

#### Scenario: Template exists
- **WHEN** the day has a template
- **THEN** the timeline renders as usual

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a empty day and header (0106)::keeps the timeline when a template exists
