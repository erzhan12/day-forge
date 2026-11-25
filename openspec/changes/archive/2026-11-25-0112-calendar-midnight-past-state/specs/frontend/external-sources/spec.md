## ADDED Requirements

### Requirement: External calendar past-state follows the saved-zone clock
The Schedule page SHALL pass the reactive saved-zone civil date from `useNowMinutes` into every ExternalEventsPanel, and the panel SHALL classify `ee-item--past` from that date and `nowMinutes`. A mounted panel SHALL restyle events when that zone rolls over midnight, without using a one-shot `todayString()` as the live today.
Enforced: frontend/src/components/ExternalEventsPanel.vue::today, frontend/src/pages/Schedule.vue::todayDate

#### Scenario: Midnight rollover without remount
- **WHEN** Schedule stays mounted and the saved-zone date advances from one civil day to the next
- **THEN** an overnight event that was current receives `ee-item--past`, even when UTC has not yet rolled over

Tests: frontend/tests/ExternalEventsPanel.test.ts::ExternalEventsPanel midnight rollover (0112)::adds ee-item--past when todayDate rolls to the next day without remounting, frontend/tests/ExternalEventsPanel.test.ts::ExternalEventsPanel midnight rollover (0112)::re-samples the saved-zone date when nowMinutes ticks across midnight without todayDate, frontend/tests/Schedule.test.ts::Schedule.vue external calendar past-state at midnight (0112)::center panel marks an overnight event past after saved-zone midnight without remounting

#### Scenario: Center and sidebar supply the date
- **WHEN** the calendar panel is placed in the center or in the classic sidebar
- **THEN** both instances receive the page clock's `todayDate` and restyle after the same rollover

Tests: frontend/tests/Schedule.test.ts::Schedule.vue external calendar past-state at midnight (0112)::center panel marks an overnight event past after saved-zone midnight without remounting, frontend/tests/Schedule.test.ts::Schedule.vue external calendar past-state at midnight (0112)::sidebar panel supplies todayDate and restyles after the same rollover

#### Scenario: Same-day clock tick
- **WHEN** `nowMinutes` advances on the same saved-zone day without remounting
- **THEN** an already-ended event stays faded and a later event stays full strength until its end

Tests: frontend/tests/ExternalEventsPanel.test.ts::ExternalEventsPanel midnight rollover (0112)::keeps same-day fading in sync with nowMinutes without remounting, frontend/tests/Schedule.test.ts::Schedule.vue external calendar past-state at midnight (0112)::same-day clock ticks keep a later event unfaded, frontend/tests/ExternalEventsPanel.test.ts::ExternalEventsPanel::dims timed events that already ended on today
