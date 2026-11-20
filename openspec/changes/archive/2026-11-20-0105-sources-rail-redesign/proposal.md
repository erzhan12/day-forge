# 0105 — Sources rail redesign and collapsible sections

## Why

The Dark 4a sources rail stretched each task section to fill the rail, used a long session label ("0 completed this session / 1"), showed a duplicate calendar header, and could not be folded. Task checkboxes also differed between the rail and the schedule blocks. See [docs/features/0105_PLAN.md](../../../docs/features/0105_PLAN.md).

## What changes

- Each rail section (Todoist, Habitica, Calendars) collapses from its header. A collapsed section keeps its title, counter and, for task sections, the progress bar; the state is remembered per section.
- The session counter reads `done / total`, or `–` before a baseline exists. Baseline capture is unchanged.
- The calendar section counts upcoming events and, while collapsed, names the next event or reports loading or unavailable sources.
- Presentation only: theme tokens instead of fixed colours, one rounded-square checkbox across all themes, a short leave animation for completed task rows, and a time-and-stripe calendar row in the rail.

## Capabilities

- `frontend/external-sources`: ADDED "Rail section collapse persistence", "Rail session progress label", "Rail calendar summary".

## Impact

Frontend only: `ExternalRail4a.vue`, new `RailSection.vue`, `ExternalEventsPanel.vue`, `TodoistTasksPanel.vue`, `HabiticaTasksSection.vue`, `TimeBlock.vue`, `TimeBlock4a.vue`, `Schedule.vue`, `app.css`, new utils for collapse storage and calendar colour, `date.ts`, `categoryColors.ts`, and the Todoist Playwright script's stale selector. No API or backend change.
