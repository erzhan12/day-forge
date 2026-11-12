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
Each tick SHALL refresh connected task sources only while the wide task rail is open, and connected calendars only while the calendar is visible (center placement, or sidebar placement on a wide open rail); disconnected sources SHALL never refresh.
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
