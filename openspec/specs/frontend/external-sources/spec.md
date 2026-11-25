# frontend/external-sources Specification

## Purpose
Client behavior of the Schedule page's external task and calendar sources (Apple CalDAV, Google Calendar, Todoist and Habitica). It covers how the integration bootstrap decides which sources load, how each dated resource arbitrates date, context and account verdicts, silent background polling and its visibility gating, optimistic task completion, the merged calendar list, and importing a calendar event as a block.

## Requirements

### Requirement: Integration bootstrap selects sources
When `integration_bootstrap` matches the current user, date and saved zone and has a new snapshot ID, the page SHALL set each source's connected state from it and load only connected sources, without account-status requests.
Enforced: frontend/src/composables/useEventImport.ts::isCurrentIntegrationBootstrap, frontend/src/composables/useExternalSources.ts::useExternalSources

#### Scenario: Connected sources
- **WHEN** the bootstrap marks some providers connected
- **THEN** exactly those lists load and no account-status request is sent

Tests: frontend/tests/useExternalSources.test.ts::useExternalSources::loads exactly the connected sources without account-status requests, frontend/tests/useExternalSources.test.ts::useExternalSources::starts no account or list requests for a disconnected bootstrap

#### Scenario: Partial date reload
- **WHEN** a partial reload keeps an old bootstrap for another date
- **THEN** the stale bootstrap is not reapplied

Tests: frontend/tests/useExternalSources.test.ts::useExternalSources::does not reapply stale bootstrap on a partial date reload, frontend/tests/useExternalSources.test.ts::useExternalSources::loads a source connected in Settings on a fresh same-date visit

### Requirement: Fallback and null-user handling
On first initialisation or a user change without a matching bootstrap, the page SHALL mark sources disconnected and read account status before loading lists; when the authenticated user becomes null it SHALL clear all rows and send no requests.
Enforced: frontend/src/composables/useExternalSources.ts::useExternalSources

#### Scenario: Mismatched bootstrap
- **WHEN** the page initialises with a bootstrap that does not match the current scope
- **THEN** account status is read before any list loads

Tests: frontend/tests/useExternalSources.test.ts::useExternalSources::falls back to account status for a mismatched bootstrap before loading lists

#### Scenario: Logout
- **WHEN** the user becomes null
- **THEN** old rows are cleared and no request is sent

Tests: frontend/tests/useExternalSources.test.ts::useExternalSources::clears old rows and sends no requests when the authenticated user becomes null, frontend/tests/useExternalSources.test.ts::useExternalSources::clears old rows when the user identity disappears

### Requirement: Dated resource arbitration
Each source SHALL commit a list response only for the latest request of the active date and context, SHALL ignore aborted or superseded requests, and SHALL clear rows when the date or saved zone changes.
Enforced: frontend/src/composables/useDatedResource.ts::useDatedResource

#### Scenario: Cross-date race
- **WHEN** responses for two dates finish out of order
- **THEN** only the most recent request is committed

Tests: frontend/tests/useTodoist.test.ts::useTodoist.fetchTasks::commits the most recent fetch (cross-date race), frontend/tests/useGoogleCalendar.test.ts::useGoogleCalendar.fetchEvents::drops a stale interleaved fetch (commits the most recent date)

#### Scenario: Superseded request
- **WHEN** a request is aborted by a newer one
- **THEN** connection state is untouched

Tests: frontend/tests/useTodoist.test.ts::useTodoist.fetchTasks::AbortError from a superseded request leaves connected/statusKnown untouched

#### Scenario: Date change after a failure
- **WHEN** a load for a new date fails
- **THEN** the previous date's rows are not shown beside the error

Tests: frontend/tests/useGoogleCalendar.test.ts::useGoogleCalendar.fetchEvents::clears stale events and accountErrors on a whole-request failure

### Requirement: Account verdicts from resource responses
A failed resource response SHALL change account state only from explicit `meta`, a success without `meta` SHALL count as connected, a disconnected verdict SHALL clear rows even during a poll, and a malformed success SHALL show `Invalid server response.`
Enforced: frontend/src/composables/useDatedResource.ts::useDatedResource

#### Scenario: Network failure on first load
- **WHEN** the first load fails without a status
- **THEN** the source stays unconnected but shows the error

Tests: frontend/tests/useTodoist.test.ts::useTodoist.fetchTasks::first-load network failure (no status) leaves connected=false but surfaces the error, frontend/tests/useTodoist.test.ts::useTodoist.fetchTasks::network failure does NOT revert an already-connected session

#### Scenario: Disconnected provider
- **WHEN** the response says the account is disconnected
- **THEN** rows are cleared and the source is disconnected without an error message

Tests: frontend/tests/useTodoist.test.ts::useTodoist.fetchTasks::503 flips connected=false (statusKnown=true) without an error message, frontend/tests/useGoogleCalendar.test.ts::useGoogleCalendar.refreshEvents::503 disconnected path still blanks events under silent refresh

#### Scenario: Status read after resource verdict
- **WHEN** an account-status read finishes after a resource response decided the account
- **THEN** the status read cannot overwrite it

Tests: frontend/tests/useDatedResource.test.ts::${adapter.name} dated resource::a status read cannot overwrite a newer resource verdict

### Requirement: Failure messages retain same-date rows
A failed load for the same date and context SHALL keep the last good rows and show an error: the provider's credentials message for a provider credential failure, an unavailable message for 502 or 504, otherwise the server error or the source's fallback text.
Enforced: frontend/src/composables/useDatedResource.ts::useDatedResource

#### Scenario: Credentials failure
- **WHEN** the first load returns a provider credentials error
- **THEN** the source is connected and shows a credentials error

Tests: frontend/tests/useTodoist.test.ts::useTodoist.fetchTasks::first-load 401 sets connected=true + statusKnown=true + a credentials error

#### Scenario: Same-date refresh failure
- **WHEN** a refresh for the date already shown fails
- **THEN** the last good rows remain visible beside the error

Tests: frontend/tests/useGoogleCalendar.test.ts::useGoogleCalendar.refreshEvents::silent whole-request failure leaves last-good events untouched, frontend/tests/useDatedResource.test.ts::${adapter.name} dated resource::preserves same-date rows on failure and clears them on date change

#### Scenario: Fallback text
- **WHEN** the error body has no message
- **THEN** the source's fixed fallback text is shown

Tests: frontend/tests/useTodoist.test.ts::useTodoist fallback-literal guard::fetchTasks surfaces the exact fallback literal on an empty errors map

### Requirement: Google all-account failure
A Google 200 response with no events and a provider or credentials failure state SHALL keep the active date's rows and show a provider banner; an empty ready response SHALL clear rows; banners SHALL clear on disconnect or scope change.
Enforced: frontend/src/composables/useGoogleCalendar.ts::useGoogleCalendar, frontend/src/composables/useDatedResource.ts::useDatedResource

#### Scenario: Ready responses
- **WHEN** a ready response is empty or partially successful
- **THEN** old rows are cleared or replaced

Tests: frontend/tests/useGoogleCalendar.test.ts::useGoogleCalendar.refreshEvents::clears old rows on a successful empty day and replaces them on partial success

#### Scenario: First all-account failure
- **WHEN** the first Google response for a day reports every account failed
- **THEN** a banner is shown without an empty-day message

Tests: frontend/tests/useExternalSources.test.ts::useExternalSources::shows a first Google all-account failure without an empty-day message, frontend/tests/useGoogleCalendar.test.ts::useGoogleCalendar.refreshEvents::disconnect clears retained events and account failures

### Requirement: Silent refresh
A silent refresh SHALL append `refresh=1`, SHALL NOT show a loading state, and SHALL replace rows only on its own atomic commit.
Enforced: frontend/src/composables/useDatedResource.ts::useDatedResource, frontend/src/composables/useGoogleCalendar.ts::useGoogleCalendar

#### Scenario: Background refresh
- **WHEN** a source refreshes silently
- **THEN** loading never turns on and rows stay populated until commit

Tests: frontend/tests/useTodoist.test.ts::useTodoist.refreshTasks::stays silent: loading never flips true and rows stay populated until the atomic commit, frontend/tests/useGoogleCalendar.test.ts::useGoogleCalendar.refreshEvents::appends refresh=1 to the events URL

### Requirement: Background poll timer
The page SHALL poll every `external_tasks_poll_interval` seconds while active, SHALL not poll when the interval is 0, SHALL skip ticks while the tab is hidden and refresh once when it becomes visible, and SHALL use the current date.
Enforced: frontend/src/composables/useExternalSourcePoll.ts::useExternalSourcePoll

#### Scenario: Interval zero
- **WHEN** the interval is 0
- **THEN** no poll runs

Tests: frontend/tests/useExternalSourcePoll.test.ts::useExternalSourcePoll::does not poll when interval is 0

#### Scenario: Hidden tab
- **WHEN** the tab is hidden and later becomes visible
- **THEN** ticks are skipped and one refresh runs on return

Tests: frontend/tests/useExternalSourcePoll.test.ts::useExternalSourcePoll::skips ticks while the document is hidden, frontend/tests/useExternalSourcePoll.test.ts::useExternalSourcePoll::refreshes once when the tab becomes visible again

#### Scenario: Inactive or unmounted
- **WHEN** the poll becomes inactive or the page unmounts
- **THEN** polling stops

Tests: frontend/tests/useExternalSourcePoll.test.ts::useExternalSourcePoll::stops polling when active becomes false, frontend/tests/useExternalSourcePoll.test.ts::useExternalSourcePoll::stops timers, visibility refreshes and reactive restarts after unmount

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

### Requirement: Optimistic task completion
Completing a task SHALL remove it from the list immediately and keep it out of GETs that began earlier; on failure only that task SHALL return to the current list with an error; a disconnected verdict SHALL clear the source.
Enforced: frontend/src/composables/useTaskCompletion.ts::useTaskCompletion

#### Scenario: Success
- **WHEN** the completion succeeds, even after a concurrent refresh re-added the task
- **THEN** the task stays removed

Tests: frontend/tests/useTodoist.test.ts::useTodoist.completeTask::optimistically removes the row and keeps it removed on ok, frontend/tests/useTodoist.test.ts::useTodoist.completeTask::success after a concurrent refresh re-added the task keeps it removed (P1 race, success side)

#### Scenario: Failure
- **WHEN** completion fails, including after a concurrent refresh replaced the list
- **THEN** only the removed task is reinserted into the current list and the error is shown

Tests: frontend/tests/useTodoist.test.ts::useTodoist.completeTask::rolls back and surfaces a no-status network error, frontend/tests/useTodoist.test.ts::useTodoist.completeTask::failure after a concurrent refresh does not clobber the refreshed list (P1 race)

#### Scenario: Session versus provider 401
- **WHEN** completion returns a session 401
- **THEN** the task is restored and the session message is shown instead of the provider credentials message

Tests: frontend/tests/useDatedResource.test.ts::${adapter.name} completion keeps a session 401 distinct from provider credentials

#### Scenario: Disconnect during completion
- **WHEN** the source is disconnected while a completion is pending
- **THEN** a late completion result cannot roll the task back

Tests: frontend/tests/useDatedResource.test.ts::${adapter.name} disconnect prevents a late completion rollback

### Requirement: Merged calendar events
The page SHALL show Apple and Google events as one list ordered by start, then title, then external UID, and SHALL show one error banner per failing provider with a per-provider retry.
Enforced: frontend/src/composables/useExternalSources.ts::useExternalSources

#### Scenario: Google failure with retained events
- **WHEN** Google reports an all-account failure beside retained events
- **THEN** the banner shows with the events and clears on account switch

Tests: frontend/tests/useExternalSources.test.ts::useExternalSources::shows a Google all-account failure beside retained events in the panel, then clears on account switch

### Requirement: Event import dialog
Choosing Add on an event SHALL open the import dialog with the matched travel rule, using bootstrapped rules or fetching them once; the dialog SHALL close and stale clicks SHALL be ignored on date, zone or user change.
Enforced: frontend/src/composables/useEventImport.ts::useEventImport

#### Scenario: Bootstrapped rules
- **WHEN** the bootstrap carries travel rules
- **THEN** no rule GET is made

Tests: frontend/tests/useEventImport.test.ts::useEventImport::uses bootstrapped rules without an initial GET

#### Scenario: Navigation during rule read
- **WHEN** the user navigates while rules are loading
- **THEN** the dialog closes and the stale click does not open it

Tests: frontend/tests/useEventImport.test.ts::useEventImport::closes the dialog on date navigation and ignores a stale click after a slow rule read, frontend/tests/useEventImport.test.ts::useEventImport::closes an import dialog and does not fetch rules after logout

### Requirement: Event import submission
The dialog SHALL compute local block times for the viewed day with clamped travel padding, prefill from a matched rule, disable Confirm for an unknown category, zero length, an event outside the day or a busy schedule, and POST exact times to the from-event endpoint.
Enforced: frontend/src/components/AddToScheduleDialog.vue::handleConfirm, frontend/src/components/AddToScheduleDialog.vue::confirmDisabled

#### Scenario: Off-grid times
- **WHEN** the user confirms a timed event
- **THEN** its exact times are posted to the from-event endpoint

Tests: frontend/tests/AddToScheduleDialog.test.ts::AddToScheduleDialog::posts the exact off-grid times to the from-event endpoint, frontend/tests/AddToScheduleDialog.test.ts::AddToScheduleDialog::prefills every field from a matched rule and applies the padding

#### Scenario: Blocked confirm
- **WHEN** the event is zero-length without padding or outside the viewed day
- **THEN** Confirm is disabled

Tests: frontend/tests/AddToScheduleDialog.test.ts::AddToScheduleDialog::blocks Confirm for a zero-length event with no travel padding, frontend/tests/AddToScheduleDialog.test.ts::AddToScheduleDialog::blocks Confirm when the event lies outside the viewed local day

#### Scenario: Outside the day window
- **WHEN** the server skips the block as outside the window
- **THEN** a window-derived notice is shown and no Undo is recorded

Tests: frontend/tests/AddToScheduleDialog.test.ts::AddToScheduleDialog::configurable day window (feature 0053)::shows the window-derived skip notice and pushes no undo for an outside_window create

#### Scenario: Rules unavailable
- **WHEN** travel rules could not load
- **THEN** a warning shows and Confirm stays available

Tests: frontend/tests/AddToScheduleDialog.test.ts::AddToScheduleDialog::warns when the travel rules could not be loaded, frontend/tests/AddToScheduleDialog.test.ts::AddToScheduleDialog::still allows Confirm while the rules are unavailable

### Requirement: Rail section collapse persistence
Toggling a Dark 4a sources rail section header SHALL flip that section's collapsed state, and each section's state SHALL be restored per section across reloads, defaulting to expanded.
Enforced: frontend/src/components/ExternalRail4a.vue::toggleSection, frontend/src/utils/externalRailSectionsStorage.ts::readExternalRailCollapsed, frontend/src/utils/externalRailSectionsStorage.ts::writeExternalRailCollapsed

#### Scenario: Collapse from the header
- **WHEN** the user activates a section header
- **THEN** the section collapses and its header reports `aria-expanded="false"`

Tests: frontend/tests/externalRail4a.test.ts::ExternalRail4a section collapse::collapses from the header, makes the body inert and keeps title, counter and bar

#### Scenario: Restore after reload
- **WHEN** the rail mounts with a stored collapsed state
- **THEN** each section opens or stays collapsed as stored, and a missing or malformed value leaves it expanded

Tests: frontend/tests/externalRail4a.test.ts::ExternalRail4a section collapse::restores each section's collapsed state from storage on mount, frontend/tests/externalRailSectionsStorage.test.ts::externalRailSectionsStorage::treats malformed JSON as all expanded, frontend/tests/externalRailSectionsStorage.test.ts::externalRailSectionsStorage::ignores non-boolean values, arrays and unknown sections

### Requirement: Rail session progress label
The rail's task counter SHALL read `done / total` from the session baseline and `–` before a baseline exists, without changing how the baseline is captured.
Enforced: frontend/src/components/ExternalRail4a.vue::progress

#### Scenario: Before a baseline
- **WHEN** no successful load has been committed for the date
- **THEN** the counter reads `–`

Tests: frontend/tests/externalRail4a.test.ts::ExternalRail4a session baseline::does not lock the idle loading=false empty list as the denominator, frontend/tests/externalRail4a.test.ts::ExternalRail4a session baseline::does not capture a failed fetch; recaptures on the next success

#### Scenario: Tasks completed this session
- **WHEN** baseline tasks leave the list after a refresh or an in-app completion
- **THEN** the counter reads the number gone over the baseline size

Tests: frontend/tests/externalRail4a.test.ts::ExternalRail4a session baseline::counts a row that vanishes after refresh as completed this session, frontend/tests/externalRail4a.test.ts::ExternalRail4a session baseline::counts an in-app complete once the parent drops the row

### Requirement: Rail calendar summary
The rail's calendar counter SHALL count events not yet past, and its collapsed peek SHALL name the in-progress or next timed event, else an all-day event, else say nothing is upcoming. It SHALL report loading or unavailable instead of an empty result while the list is loading or failed.
Enforced: frontend/src/components/ExternalRail4a.vue::calendarSummary

#### Scenario: Next and in-progress events
- **WHEN** today's list has an event in progress or a later timed event
- **THEN** the peek reads `Now · Title` for the started one, otherwise `Next · HH:MM Title`

Tests: frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::names the next timed event and counts only events not yet past, frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::says Now for an in-progress event, including an overnight one that began yesterday, frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::never says Now while the clock is unknown

#### Scenario: Loading or failed with no events
- **WHEN** the list is empty while loading, or empty with provider or account errors
- **THEN** the counter reads `–` and the peek reports loading or that calendars are unavailable

Tests: frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::reports loading, not an empty day, while the first load runs, frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::reports unavailable, not an empty day, when every source failed, frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::says nothing is upcoming after a successful empty load

#### Scenario: Partial failure beside events
- **WHEN** events are present and a provider or account failed
- **THEN** the peek appends how many sources are unavailable, counting Google's all-account failure once

Tests: frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::counts a Google all-account failure beside Apple rows once, frontend/tests/externalRail4a.test.ts::ExternalRail4a calendar summary::flags a partial account failure beside healthy events

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
