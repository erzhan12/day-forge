## ADDED Requirements

### Requirement: Calendar events stay off the timeline
A calendar event SHALL enter the schedule timeline only as a block created through the explicit Add to schedule import; the timeline and its free gaps SHALL be computed from stored blocks alone, and the page view SHALL NOT fetch provider events.
Enforced: frontend/src/composables/useTimelinePresentation.ts::useTimelinePresentation, frontend/src/composables/useEventImport.ts::useEventImport, backend/schedules/views.py::schedule_view

#### Scenario: Event not added
- **WHEN** a connected calendar has an event inside a free gap
- **THEN** the timeline renders no item for it and the gap stays one free interval

Tests: frontend/tests/Schedule.test.ts::Schedule.vue calendar events stay off the timeline (0106)::renders no timeline item for an event that was not added, frontend/tests/Schedule.test.ts::Schedule.vue calendar events stay off the timeline (0106)::keeps 12:10–15:00 as one free gap of 170 minutes, backend/tests/test_schedule_view_props.py::test_blocks_prop_excludes_unimported_calendar_events

#### Scenario: Explicit import
- **WHEN** the user activates Add to schedule on an event
- **THEN** the import dialog opens and no block exists until the dialog creates one

Tests: frontend/tests/Schedule.test.ts::Schedule.vue calendar events stay off the timeline (0106)::shows the event only inside the sources rail with an Add to schedule button, frontend/tests/Schedule.test.ts::Schedule.vue calendar events stay off the timeline (0106)::opens the import dialog on Add to schedule and creates no block by itself

### Requirement: Rail event source label
Rail calendar rows and the Dark 4a centre panel SHALL label an event with its calendar name, else its account label, shortening an email to its local part, joined with its duration, and SHALL offer a text-only Add to schedule button for timed events; other layouts SHALL keep their copy.
Enforced: frontend/src/utils/eventSourceLabel.ts::eventSourceLabel, frontend/src/components/ExternalEventsPanel.vue::railRows

#### Scenario: Google calendar row
- **WHEN** a Google event comes from the calendar "Team"
- **THEN** the row reads `Team · 15m` and keeps the account email only as a hover title

Tests: frontend/tests/ExternalEventsPanel.test.ts::ExternalEventsPanel embedded (sources rail)::shows the calendar name, not the account email, in the rail, frontend/tests/eventSourceLabel.test.ts::eventSourceLabel (0106)::shows the local part when the name is an email, frontend/tests/eventSourceLabel.test.ts::eventSourceLabel (0106)::never invents Personal

#### Scenario: Layouts
- **WHEN** the centre panel renders in Dark 4a or in another layout
- **THEN** Dark 4a uses the rail copy and button, and other layouts keep the chip row and `+ Add to schedule`

Tests: frontend/tests/ExternalEventsPanel.test.ts::ExternalEventsPanel centre variant by layout (0106)::applies the calendar name and Add to schedule to the centre variant in Dark 4a, frontend/tests/ExternalEventsPanel.test.ts::ExternalEventsPanel centre variant by layout (0106)::keeps the default-variant copy unchanged outside Dark 4a

## MODIFIED Requirements

### Requirement: Poll fan-out by visible branch
Each tick SHALL refresh connected task sources only while the wide task rail is open, and connected calendars only while the calendar is visible (center placement, sidebar placement on a wide open rail, or Dark 4a below 1024 px, where the panel falls back to the center without rewriting the stored placement); disconnected sources SHALL never refresh.
Enforced: frontend/src/composables/useExternalSources.ts::useExternalSources

#### Scenario: Calendar in center on narrow screen
- **WHEN** the calendar is placed in the center with a connected calendar on a narrow viewport
- **THEN** the poll is active and refreshes calendar events

Tests: frontend/tests/Schedule.test.ts::Schedule.vue external source poll gating (feature 0031)::center placement + narrow viewport + calendar connected → poll active and fans out to refreshEvents

#### Scenario: Collapsed sidebar
- **WHEN** the calendar is in a collapsed sidebar
- **THEN** the calendar branch is off

Tests: frontend/tests/Schedule.test.ts::Schedule.vue external source poll gating (feature 0031)::sidebar placement + wide + collapsed + calendar connected → calendars branch false

#### Scenario: Branch isolation
- **WHEN** only one branch is active
- **THEN** only that branch's sources refresh and disconnected providers never do

Tests: frontend/tests/Schedule.test.ts::Schedule.vue external source poll gating (feature 0031)::tasks-only tick does not call calendar refresh, frontend/tests/Schedule.test.ts::Schedule.vue external source poll gating (feature 0031)::disconnected provider's refreshEvents is never called

#### Scenario: Dark 4a narrow fallback
- **WHEN** a Dark 4a viewport is below 1024 px with sidebar placement and a connected calendar
- **THEN** the panel renders under the timeline and is polled, the stored placement stays, and Classic keeps its narrow behaviour

Tests: frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a narrow calendar fallback (0106)::renders and polls the calendar panel below 1024px in Dark 4a with sidebar placement, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a narrow calendar fallback (0106)::returns to the stored placement when resized to wide, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a narrow calendar fallback (0106)::keeps narrow behaviour unchanged in classic
