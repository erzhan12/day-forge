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
