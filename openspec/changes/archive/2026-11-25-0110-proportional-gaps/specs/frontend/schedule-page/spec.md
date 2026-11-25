## MODIFIED Requirements

### Requirement: Dark 4a stack layout
The Dark 4a timeline SHALL stack items without overlaps or holes, render blocks at least 28 px tall, keep a gap between two blocks on the true scale, cap edge gaps and spacers at the edge-stub height, merge contiguous free gaps, and place hour labels and the now line through one axis map. Other layouts SHALL keep the linear scale.
Enforced: frontend/src/utils/timelineStack.ts::buildTimelineStack, frontend/src/composables/useTimelinePresentation.ts::createTimelinePresentation

#### Scenario: Short block and long gap
- **WHEN** a day has a 5-minute block and a 170-minute free gap between two blocks
- **THEN** the block renders 28 px tall, the gap 340 px, and every later item moves down accordingly

Tests: frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::heights::raises a 5-minute block to 28px, frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::heights::keeps a 170-minute mid-day gap on the scale, frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::stacking::stacks items with no overlap and no hole

#### Scenario: Edge gaps and spacers stay capped
- **WHEN** a long free gap touches the window start or end, or a spacer covers out-of-window time
- **THEN** it renders at most 60 px tall

Tests: frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::heights::caps a long gap at 60px when it touches a window edge, frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::heights::caps a spacer at 60px

#### Scenario: Clock moves through the day
- **WHEN** the current time falls inside a gap or moves past the last block
- **THEN** the now line sits on the true scale inside a mid-day gap and proportionally inside a capped edge row, and the column height does not change

Tests: frontend/tests/timelinePresentation.test.ts::timeline presentation in stack mode (0106)::places the now line on the true scale inside a mid-day gap, frontend/tests/timelinePresentation.test.ts::timeline presentation in stack mode (0106)::places the now line inside a capped trailing gap proportionally, frontend/tests/timelineStack.test.ts::buildTimelineStack (0106)::linear equivalence and fixture::keeps the fixture at 898px at any clock time

#### Scenario: Classic layout
- **WHEN** the theme is not Dark 4a
- **THEN** the timeline keeps its linear geometry

Tests: frontend/tests/timelinePresentation.test.ts::timeline presentation in stack mode (0106)::linear mode is unchanged

### Requirement: Dark 4a gap row
A Dark 4a free gap SHALL read `Free · <duration>` with its range and a visible add affordance, and activating it SHALL open the Add Block form with the gap's 5-minute-grid range, also after a Cancel; a gap without a 5-minute slot SHALL be inert.
Enforced: frontend/src/components/GapSlot4a.vue::activate, frontend/src/components/AddBlockForm.vue::addRequestId

#### Scenario: Label and add
- **WHEN** the user activates a 170-minute gap row
- **THEN** it reads `Free · 2h 50m` and `12:10–15:00` and emits the snapped range

Tests: frontend/tests/GapSlot4a.test.ts::GapSlot4a (0106)::shows Free · 2h 50m and 12:10–15:00 on a gap row, frontend/tests/GapSlot4a.test.ts::GapSlot4a (0106)::emits the grid-snapped gap range on click and on Enter, frontend/tests/GapSlot4a.test.ts::GapSlot4a (0106)::is inert when the gap has no 5-minute slot

#### Scenario: Reopen after Cancel
- **WHEN** the same gap is activated again after Cancel
- **THEN** the form opens again in Dark 4a and the classic handler keeps today's behaviour

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a gap add (0106)::reopens the form when the same gap is activated after Cancel, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a gap add (0106)::keeps the classic gap handler unchanged
