## MODIFIED Requirements

### Requirement: Drag cancellation and frozen geometry
A drag SHALL freeze render bounds, the now marker, the day window and, in the Dark 4a stack layout, the axis map at start, convert pointer pixels through that map, clamp the preview to the window, and be cancelled without a write by Escape, viewport resize, a context change or unmount. Stack-layout drag SHALL NOT start on a day with overlapping blocks.
Enforced: frontend/src/composables/useDrag.ts::useDrag, frontend/src/composables/useDrag.ts::hasOverlappingBlocks

#### Scenario: Unmount mid-drag
- **WHEN** the component unmounts during a drag
- **THEN** the gesture is cancelled without committing

Tests: frontend/tests/useDrag.test.ts::useDrag lifecycle::cancels an active gesture on component unmount without committing or leaving listeners

#### Scenario: Frozen state
- **WHEN** a drag starts and ends
- **THEN** frozen bounds, now and axis map are set and then cleared

Tests: frontend/tests/useDrag.test.ts::useDrag frozen render bounds::sets frozenRenderBounds on startDrag and clears on endDrag, frontend/tests/useDrag.test.ts::useDrag frozen render bounds::sets frozenNowMinutes from getNow on startDrag and clears on endDrag, frontend/tests/useDrag.test.ts::useDrag on the stack axis map (0106)::clears the frozen map on drop, cancel and context change

#### Scenario: Narrowed window
- **WHEN** the day window starts later than the default
- **THEN** the preview never starts before the window start

Tests: frontend/tests/useDrag.test.ts::useDrag off-grid geometry and payload (feature 0026)::clamps the drop preview to the window start under a narrowed window (feature 0053)

#### Scenario: Pointer through the stack map
- **WHEN** the pointer moves over a capped gap or the leading stub in the stack layout
- **THEN** the preview time comes from the frozen map, reaches the window start, and the drop commits the shown time

Tests: frontend/tests/useDrag.test.ts::useDrag on the stack axis map (0106)::converts pointer pixels through the frozen axis map, frontend/tests/useDrag.test.ts::useDrag on the stack axis map (0106)::reaches the window start through the leading stub, frontend/tests/useDrag.test.ts::useDrag on the stack axis map (0106)::commits the ghost label time for a drop near the end of a capped gap

#### Scenario: Overlapping legacy blocks
- **WHEN** stored blocks overlap in time
- **THEN** a stack-layout drag does not start

Tests: frontend/tests/useDrag.test.ts::useDrag on the stack axis map (0106)::is disabled on a day with overlapping blocks
