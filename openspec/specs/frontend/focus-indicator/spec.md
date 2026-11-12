# frontend/focus-indicator Specification

## Purpose
Client behavior of the focus indicator and block-boundary alerts on the Schedule page. It covers how the app-root controller derives the active, pause, day-finished and neutral states from a published schedule snapshot, the Document Picture-in-Picture window lifecycle and its privacy limits, restore intent, and the sound and desktop notifications fired when the saved-zone clock crosses a block start or end.

## Requirements

### Requirement: Saved-zone minute clock
The client SHALL sample the current minute in the saved schedule time zone every 60 seconds and on tab visibility, exposing a minute and date only while the viewed date is today in that zone and null otherwise.
Enforced: frontend/src/composables/useNowMinutes.ts::useNowMinutes

#### Scenario: Browser zone differs from saved zone
- **WHEN** the browser zone and the saved zone disagree about the current time
- **THEN** the sampled minute and today date follow the saved zone

Tests: frontend/tests/useNowMinutes.test.ts::useNowMinutes::uses one instant in the saved zone, independent of the browser zone

#### Scenario: Navigating into today or changing the zone
- **WHEN** the viewed date becomes today or the saved zone changes
- **THEN** the clock resamples immediately instead of waiting for the next tick

Tests: frontend/tests/useNowMinutes.test.ts::useNowMinutes::refreshes immediately when navigating into today and when the saved zone changes

#### Scenario: Viewed date is not today
- **WHEN** the viewed date differs from today in the saved zone
- **THEN** the minute and date are null while the timer keeps running for later navigation or midnight

Tests: frontend/tests/useNowMinutes.test.ts::useNowMinutes::keeps one timer while off-today, so a future date enters today at midnight, frontend/tests/useNowMinutes.test.ts::useNowMinutes::leaves yesterday when midnight passes and keeps the timer for later navigation

#### Scenario: Hidden tab returns after midnight
- **WHEN** a hidden tab becomes visible after midnight
- **THEN** the clock resamples immediately

Tests: frontend/tests/useNowMinutes.test.ts::useNowMinutes::resamples when a hidden tab becomes visible after midnight

### Requirement: Active block derivation
The indicator SHALL be active only for the uncompleted block containing the current minute (half-open interval, overlap winner by start then sort_order) on today, with a finite positive duration.
Enforced: frontend/src/utils/focusIndicator.ts::activeUnfinishedBlock, frontend/src/composables/useFocusIndicatorController.ts::useFocusIndicatorController

#### Scenario: Current block is completed
- **WHEN** the block containing the current minute is completed
- **THEN** the indicator is not active

Tests: frontend/tests/focusIndicator.test.ts::activeUnfinishedBlock::returns null when the current block is completed, frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::is neutral when the current block is completed

#### Scenario: Off-today
- **WHEN** the clock date is null because the viewed day is not today
- **THEN** no block is active

Tests: frontend/tests/focusIndicator.test.ts::activeUnfinishedBlock::returns null when nowDate is null (off-today)

#### Scenario: Overlapping blocks
- **WHEN** two blocks contain the current minute
- **THEN** the earliest start wins and equal starts resolve by sort_order

Tests: frontend/tests/focusIndicator.test.ts::activeUnfinishedBlock::resolves same-start overlap by sort_order

### Requirement: Active progress percent
The indicator SHALL report active progress as the elapsed fraction of the block clamped to 0..1 and rounded to an integer percent, and SHALL treat a zero, negative or unparseable duration as inactive.
Enforced: frontend/src/utils/focusIndicator.ts::progressRatio, frontend/src/utils/focusIndicator.ts::progressPercentFromRatio

#### Scenario: Mid-block
- **WHEN** the current minute is halfway through the active block
- **THEN** the percent is 50

Tests: frontend/tests/focusIndicator.test.ts::progressRatio::returns a clamped 0..1 ratio at mid-block

#### Scenario: Zero-length block
- **WHEN** the containing block has zero duration
- **THEN** no ratio is produced and the indicator stays neutral

Tests: frontend/tests/focusIndicator.test.ts::progressRatio::returns null for zero duration (fail closed to neutral)

### Requirement: Next block selection
When not active, the indicator SHALL choose the block with the nearest start strictly after now (ties by sort_order, completed blocks included), and SHALL choose none when any start is unparseable or the chosen block has no positive duration.
Enforced: frontend/src/utils/focusIndicator.ts::nextBlockAfter

#### Scenario: Equal starts
- **WHEN** two future blocks share the nearest start
- **THEN** the lower sort_order is chosen even if it is completed

Tests: frontend/tests/focusIndicator.test.ts::nextBlockAfter::breaks equal starts by sort_order and includes completed future blocks

#### Scenario: Block starting exactly now
- **WHEN** a block starts at the current minute
- **THEN** it is not treated as next

Tests: frontend/tests/focusIndicator.test.ts::nextBlockAfter::excludes a block that starts exactly now and returns null after the final start

#### Scenario: Invalid start or candidate
- **WHEN** any start is unparseable or the nearest candidate has an invalid duration
- **THEN** no next block is chosen rather than skipping to a later one

Tests: frontend/tests/focusIndicator.test.ts::nextBlockAfter::fails closed when any start is unparseable, even for an irrelevant past block, frontend/tests/focusIndicator.test.ts::nextBlockAfter::does not skip an invalid equal-start sibling to a valid one

### Requirement: Pause progress
In a gap before a next block, the indicator SHALL measure pause progress from the latest block end at or before now to the next start, and SHALL report no fill before the first block or when any block end is unparseable or inverted.
Enforced: frontend/src/utils/focusIndicator.ts::pauseWindow, frontend/src/utils/focusIndicator.ts::pauseProgressRatio

#### Scenario: Between two blocks
- **WHEN** now lies between a finished block and the next block
- **THEN** the pause spans the finished block's end to the next block's start

Tests: frontend/tests/focusIndicator.test.ts::pauseWindow::spans the previous block's end to the next block's start, frontend/tests/focusIndicator.test.ts::pauseProgressRatio::returns the clamped elapsed fraction

#### Scenario: Before the first block
- **WHEN** no block has ended yet
- **THEN** the pause has no origin and no measurable fill

Tests: frontend/tests/focusIndicator.test.ts::pauseWindow::has a null start before the day's first block (no honest pause origin)

#### Scenario: Inverted block
- **WHEN** any block ends before it starts
- **THEN** no pause window is produced

Tests: frontend/tests/focusIndicator.test.ts::pauseWindow::fails closed when any block is inverted (end < start)

### Requirement: Day finished state
The indicator SHALL report the day finished only on today when the day has at least one block and every block has well-formed times and has ended at or before now.
Enforced: frontend/src/utils/focusIndicator.ts::isDayFinished

#### Scenario: All blocks ended
- **WHEN** every block ends at or before the current minute
- **THEN** the day is finished

Tests: frontend/tests/focusIndicator.test.ts::isDayFinished::is true once every block has ended, frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::reports the day finished once every block has ended

#### Scenario: Empty or malformed day
- **WHEN** the day has no blocks or a block has malformed times
- **THEN** the day is not reported finished

Tests: frontend/tests/focusIndicator.test.ts::isDayFinished::is false for an empty day — nothing was scheduled to finish, frontend/tests/focusIndicator.test.ts::isDayFinished::fails closed on malformed data rather than claiming a finished day

#### Scenario: Inside a completed final block
- **WHEN** now sits inside a completed final block
- **THEN** the indicator is neutral and not day-finished

Tests: frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::stays neutral, not day-finished, while sitting inside a completed final block, frontend/tests/focusIndicator.test.ts::isDayFinished::is false while any block still has time left, completed or not

### Requirement: Active PiP body
In the active state the PiP view SHALL show the block title (`Untitled` when empty), the timeline's remaining-time copy, and a progressbar whose rail and fill use the block's category colour or a neutral grey fallback.
Enforced: frontend/src/components/FocusIndicatorView.vue::accentColor, frontend/src/components/FocusIndicatorView.vue::remainingLabelFor

#### Scenario: Active block shown
- **WHEN** the indicator is active
- **THEN** the body shows the title and remaining minutes and a progressbar carrying the elapsed percent

Tests: frontend/tests/FocusIndicatorView.test.ts::FocusIndicatorView — active state::shows the block title and the timeline's remaining-minutes copy, frontend/tests/FocusIndicatorView.test.ts::FocusIndicatorView — active state::renders an accessible progressbar carrying the elapsed percent

#### Scenario: Category colour
- **WHEN** the active block's category has a colour
- **THEN** the rail and fill use that colour and repaint when only the colour changes

Tests: frontend/tests/FocusIndicatorView.test.ts::FocusIndicatorView — active state::paints the rail and the fill in the category colour, frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::repaints the rail when only the category's colour changes

### Requirement: Pause and neutral PiP body
When not active the PiP view SHALL show a pause label with the next title and countdown, or `day finished`, or a neutral state; it SHALL drop the next block when its title is null or countdown is not positive and SHALL use no category colour.
Enforced: frontend/src/components/FocusIndicatorView.vue::nextBlockLabel, frontend/src/components/FocusIndicatorView.vue::pauseMeasurable

#### Scenario: Idle gap
- **WHEN** now is in a gap before a later block
- **THEN** the body shows the pause label, an arrow, the next title and its countdown

Tests: frontend/tests/FocusIndicatorView.test.ts::FocusIndicatorView — pause state::labels the pause and names the next block with an arrow, frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::bridges an idle gap to PiP with the nearest future title and live countdown

#### Scenario: Null next title
- **WHEN** the next title is null even with a positive countdown
- **THEN** no next block is shown

Tests: frontend/tests/FocusIndicatorView.test.ts::FocusIndicatorView — pause state::treats a null title as no next block even with a positive countdown

#### Scenario: Day finished
- **WHEN** the day is finished
- **THEN** the next block is suppressed and the track does not measure progress

Tests: frontend/tests/FocusIndicatorView.test.ts::FocusIndicatorView — pause state::suppresses a next block entirely once the day is finished, frontend/tests/FocusIndicatorView.test.ts::FocusIndicatorView — pause state::shows the day-finished label with an empty, non-measuring track

### Requirement: PiP privacy
The PiP window SHALL keep its document title `Focus` in every state and SHALL never show the date, wall-clock times or a raw category slug, and SHALL contain no control of its own.
Enforced: frontend/src/composables/useFocusIndicator.ts::PIP_TITLE, frontend/src/components/FocusIndicatorView.vue::stateName

#### Scenario: Active block in PiP
- **WHEN** the PiP shows an active block
- **THEN** it shows title and countdown but no clock times or date

Tests: frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::shows the block title and countdown but never clock times or the date, frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::sets a generic PiP document.title (never a block title)

#### Scenario: No in-window control
- **WHEN** the PiP document is rendered
- **THEN** it contains no button; dismissal is the browser chrome or header Hide

Tests: frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::puts no control inside the PiP document — the chrome and Hide own dismissal

### Requirement: PiP open lifecycle
The client SHALL open the PiP only when Document Picture-in-Picture is supported, as a single 280x60 window, ignoring opens while one is open or pending, and SHALL inject its own styles and mount a live view.
Enforced: frontend/src/composables/useFocusIndicator.ts::useFocusIndicator

#### Scenario: Unsupported browser
- **WHEN** the API is absent
- **THEN** open is a no-op and the header button is disabled as unsupported

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::reports supported=false and open() is a non-throwing no-op when the API is absent, frontend/tests/ShowIndicatorButton.test.ts::ShowIndicatorButton::is disabled with a concise explanation when unsupported

#### Scenario: Double click
- **WHEN** open is called again while the first request is pending
- **THEN** only one window is requested

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::open() creates exactly one window; a second call while pending does not re-request

#### Scenario: Live repaint
- **WHEN** the reactive indicator source changes
- **THEN** the open PiP repaints

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::keeps the PiP view live: aria-valuenow updates when the reactive source changes, frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::injects the view layout stylesheet into the PiP document (not only html/body chrome)

### Requirement: PiP open failure and orphans
A failed current open SHALL close any partial window and show `Could not open indicator. Please try again.` for 5 seconds, and a request settling after Hide, disposal or a newer open SHALL close its own window without an error or touching the newer request.
Enforced: frontend/src/composables/useFocusIndicator.ts::useFocusIndicator

#### Scenario: Rejected request
- **WHEN** the PiP request is rejected
- **THEN** a generic error appears beside the header control and clears after a brief interval

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::surfaces a generic error when the PiP request is rejected, frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::dismisses the open error after a brief interval

#### Scenario: Request resolves after Hide
- **WHEN** Hide runs while a request is pending and the request later resolves
- **THEN** the orphaned window is closed

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::cleanup() while the request is still pending closes the orphaned window on resolve

#### Scenario: Stale rejection after reopen
- **WHEN** an old request rejects after a newer open succeeded
- **THEN** the new window stays and no error is shown

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::a stale rejection after cleanup()+reopen leaves the new window and shows no error

### Requirement: Restore intent
A successful open SHALL persist restore intent; header Hide SHALL close and clear it; browser-chrome close, reload and owner disposal SHALL keep it, and stored intent SHALL only offer a restore affordance, never open automatically.
Enforced: frontend/src/composables/useFocusIndicator.ts::useFocusIndicator, frontend/src/utils/focusIndicatorStorage.ts::readFocusIndicatorShouldBeOpen

#### Scenario: Hide versus disposal
- **WHEN** the user clicks Hide or the owner is disposed
- **THEN** Hide clears intent while disposal preserves it

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::dispose preserves intent, while cleanup (explicit close) clears intent, frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::Hide explicitly closes and clears intent, then Show opens again

#### Scenario: Browser chrome close
- **WHEN** the PiP fires pagehide
- **THEN** intent is preserved and the header returns to Show

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::preserves restore intent on any PiP pagehide (browser chrome / Back to tab), frontend/tests/scheduleFocusIndicator.test.ts::Schedule.vue focus indicator::browser PiP pagehide (Back to tab) preserves restore intent and returns the header to Show

#### Scenario: Stored intent on load
- **WHEN** intent is stored and the PiP is closed
- **THEN** a restore affordance is exposed and nothing opens on mount

Tests: frontend/tests/useFocusIndicator.test.ts::useFocusIndicator::exposes a stored restore intent while the supported PiP is closed, frontend/tests/ShowIndicatorButton.test.ts::ShowIndicatorButton::does not auto-emit on mount

#### Scenario: Malformed storage
- **WHEN** the stored intent is anything other than literal JSON true
- **THEN** it is read as no intent

Tests: frontend/tests/focusIndicatorStorage.test.ts::focus indicator restore storage::accepts only literal JSON true and safely clears intent

### Requirement: Root ownership and publication generation
The app root SHALL own the PiP and retain copied snapshots published by Schedule; on Login, a null user or a user change it SHALL advance the generation, clear the snapshot and close the PiP clearing intent, rejecting later stale publications.
Enforced: frontend/src/composables/useFocusIndicatorController.ts::useFocusIndicatorController, frontend/src/composables/useFocusIndicatorController.ts::publishIfGenerationMatches

#### Scenario: Login transition
- **WHEN** the page component becomes Login
- **THEN** the PiP closes and retained schedule data is dropped

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::closes and drops retained schedule data on the definite Login transition, frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::does not restore the departing publisher snapshot after the root clears it for Login

#### Scenario: Account switch on Schedule
- **WHEN** the user ID changes while the component stays Schedule
- **THEN** the previous user's retained data is dropped

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::drops the previous user's retained data even when the component stays Schedule

#### Scenario: Route change
- **WHEN** the Schedule publisher unmounts on an ordinary navigation
- **THEN** the PiP stays open and keeps rendering from the retained snapshot

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::keeps one PiP open through publisher unmount and renders its later idle state, frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::does not treat an uninitialized page component as logout

### Requirement: Boundary crossing detection
The boundary detector SHALL fire each block start and end whose minute lies in (previous sample, now] on today, firing only boundaries exactly at now on the first sample and nothing on a backward clock step.
Enforced: frontend/src/composables/useBlockBoundaryDetector.ts::useBlockBoundaryDetector

#### Scenario: Coalesced tick
- **WHEN** the sampler jumps a few minutes forward within the horizon
- **THEN** every leapt boundary fires

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::7. coalesced multi-minute jump fires every boundary it leapt over

#### Scenario: First sample of a date
- **WHEN** the detector mounts mid-day or a new date starts
- **THEN** earlier boundaries are not back-filled but a boundary at the current minute fires once

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::8. first tick of a date does not back-fill earlier boundaries, frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::14. pre-populated nowMinutes at mount fires start boundary exactly once

#### Scenario: Off-today or clock moved back
- **WHEN** the clock date is null or the minute moves backward
- **THEN** nothing fires

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::10. off-today (nowDate null) never fires, frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::11. backward clock step fires nothing (no stale burst)

### Requirement: Suspension horizon
After a same-day forward jump larger than 5 minutes, the detector SHALL fire only boundaries in (now - 5, now].
Enforced: frontend/src/composables/useBlockBoundaryDetector.ts::MAX_COALESCE_GAP_MINUTES

#### Scenario: Multi-hour resume
- **WHEN** a suspended tab resumes hours later on the same day
- **THEN** stale boundaries do not replay and only the last five minutes fire

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::18. multi-hour same-day jump does not replay stale boundaries, frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::19. resume jump fires only boundaries within the staleness horizon

#### Scenario: Jump equal to horizon
- **WHEN** the jump equals 5 minutes
- **THEN** every leapt boundary still fires

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::20. modest coalesced jump (== horizon) still replays every leapt boundary

### Requirement: Boundary deduplication
Each channel SHALL fire a boundary at most once per date keyed by type, block ID, date and boundary minute, so a re-timed block fires its new boundary, and SHALL reset its keys and cursor on date change.
Enforced: frontend/src/composables/useBlockBoundaryDetector.ts::useBlockBoundaryDetector

#### Scenario: Re-entry
- **WHEN** the same boundary is observed again
- **THEN** it does not fire twice

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::4. no double-fire for the same boundary on re-entry

#### Scenario: Re-timed block
- **WHEN** a block whose boundary already fired is moved to a new minute
- **THEN** the new boundary fires

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::12. a re-timed boundary fires again with the NEW minute

### Requirement: Channel enablement and independent cursors
A disabled channel SHALL fire nothing and not advance its cursor, re-enabling SHALL not back-fire boundaries passed while off, and sound and desktop SHALL keep independent cursors on the shared clock.
Enforced: frontend/src/composables/useBlockBoundaryDetector.ts::useBlockBoundaryDetector

#### Scenario: Re-enable after a gap
- **WHEN** a channel is re-enabled after boundaries passed while disabled
- **THEN** those boundaries do not fire

Tests: frontend/tests/useBlockBoundaryDetector.test.ts::useBlockBoundaryDetector::13. re-enabling after a disabled gap does not back-fire skipped boundaries

#### Scenario: One channel disabled
- **WHEN** the desktop channel is disabled mid-run
- **THEN** sound keeps firing and desktop does not

Tests: frontend/tests/useDesktopNotifications.test.ts::independent cursors: disabling desktop leaves sound firing::sound fires and desktop does not after the desktop channel is disabled mid-run

### Requirement: Sound chimes
When enabled, sound notifications SHALL play a rising two-note chime at a block start and a falling one at a block end; enabling SHALL persist the setting and unlock audio, and audio failures SHALL not throw.
Enforced: frontend/src/composables/useSoundNotifications.ts::useSoundNotificationSetting, frontend/src/composables/useSoundNotifications.ts::useSoundNotifications

#### Scenario: Start and end chimes
- **WHEN** a start and an end boundary fire
- **THEN** a rising and a distinct falling chime play

Tests: frontend/tests/useSoundNotifications.test.ts::useSoundNotifications — chime synthesis::start boundary fires a rising chime, frontend/tests/useSoundNotifications.test.ts::useSoundNotifications — chime synthesis::end boundary fires a falling chime (distinct from start)

#### Scenario: Enable sound
- **WHEN** the user enables sound
- **THEN** the setting persists and the audio context resumes without throwing on rejection

Tests: frontend/tests/useSoundNotifications.test.ts::useSoundNotificationSetting — autoplay unlock + persistence::14. setEnabled(true) resumes the singleton and persists true, frontend/tests/useSoundNotifications.test.ts::useSoundNotificationSetting — autoplay unlock + persistence::14b. a rejected resume() does not throw out of setEnabled

### Requirement: Desktop notification permission
Enabling desktop notifications SHALL request permission and persist only a grant; a later off toggle SHALL win over a late permission result, and on mount a stored on setting SHALL be kept only with granted permission in a supporting browser.
Enforced: frontend/src/composables/useDesktopNotifications.ts::useDesktopNotificationSetting

#### Scenario: Grant or denial
- **WHEN** the user enables desktop notifications and permission is granted or denied
- **THEN** a grant is persisted and enabled, while a denial is not persisted and shows a denial hint

Tests: frontend/tests/useDesktopNotifications.test.ts::useDesktopNotificationSetting — permission flow::setEnabled(true) + granted → storage true, enabled true, frontend/tests/useDesktopNotifications.test.ts::useDesktopNotificationSetting — permission flow::setEnabled(true) + denied → not persisted, permissionDenied true

#### Scenario: Late result after turning off
- **WHEN** permission resolves after the user turned the setting off
- **THEN** the setting stays off with no denial hint

Tests: frontend/tests/useDesktopNotifications.test.ts::useDesktopNotificationSetting — permission flow::stale-request race: late grant after setEnabled(false) stays OFF, no spurious hint, frontend/tests/useDesktopNotifications.test.ts::useDesktopNotificationSetting — permission flow::stale-request race: late DENIAL after setEnabled(false) leaves no spurious hint

#### Scenario: Revoked permission on mount
- **WHEN** storage says on but permission is not granted or the API is missing
- **THEN** the setting is off and the stored flag is cleared

Tests: frontend/tests/useDesktopNotifications.test.ts::useDesktopNotificationSetting — permission flow::mount revalidation: storage true but permission denied → off + flag cleared, frontend/tests/useDesktopNotifications.test.ts::useDesktopNotificationSetting — permission flow::unsupported browser on mount with stale storage true → off + flag cleared

#### Scenario: Granted on mount
- **WHEN** storage says on and permission is granted
- **THEN** the setting is on

Tests: frontend/tests/useDesktopNotifications.test.ts::useDesktopNotificationSetting — permission flow::mount: storage true + permission granted → enabled true

### Requirement: Desktop notification delivery
With granted permission a boundary SHALL show a notification titled `Block started` or `Block ended`, tagged by type, block, date and minute, whose click focuses the tab and closes it; without permission or on constructor errors it SHALL do nothing.
Enforced: frontend/src/composables/useDesktopNotifications.ts::showDesktopNotification, frontend/src/utils/desktopNotificationCopy.ts::desktopNotificationTitle

#### Scenario: Start boundary
- **WHEN** a start boundary fires with permission granted
- **THEN** one notification with the start title, body and tag is shown

Tests: frontend/tests/useDesktopNotifications.test.ts::useDesktopNotifications — detector parity::start boundary → one notification, title/body/tag match copy spec

#### Scenario: Two blocks share a start
- **WHEN** two blocks start at the same minute with permission granted
- **THEN** two notifications with distinct tags are shown

Tests: frontend/tests/useDesktopNotifications.test.ts::useDesktopNotifications — detector parity::two blocks sharing a start minute → two notifications (distinct tags)

#### Scenario: Click
- **WHEN** the user clicks the notification
- **THEN** the tab is focused and the notification closes

Tests: frontend/tests/useDesktopNotifications.test.ts::showDesktopNotification::onclick focuses the tab and closes the notification

#### Scenario: Permission not granted
- **WHEN** permission is not granted
- **THEN** no notification is constructed

Tests: frontend/tests/useDesktopNotifications.test.ts::showDesktopNotification::no-ops when permission !== granted
