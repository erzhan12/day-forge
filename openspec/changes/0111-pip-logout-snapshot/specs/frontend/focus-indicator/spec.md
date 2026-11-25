## MODIFIED Requirements

### Requirement: Root ownership and publication generation
The app root SHALL own the PiP and retain copied snapshots published by Schedule through generation-matched publication only; on Login, a null user or a user change it SHALL advance the generation, clear the snapshot and close the PiP clearing intent, rejecting later stale publications and any write while Login or null-user remains in force.
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

#### Scenario: Ungated publish removed
- **WHEN** a caller inspects the root Focus Indicator controller after mount
- **THEN** there is no public ungated `publish` entry point

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::refuses an ungated publish after Login (issue #212), frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::refuses an ungated publish after an account switch (issue #212)

#### Scenario: Current-generation refuse on Login
- **WHEN** Login has cleared the snapshot and a caller presents the post-clear generation
- **THEN** `publishIfGenerationMatches` returns false and retained blocks and categories stay empty

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::returns false from publishIfGenerationMatches after Login with the post-clear generation

#### Scenario: Null-user clear and refuse
- **WHEN** `auth_user_id` becomes null while the component stays Schedule
- **THEN** the PiP closes, retained data is dropped, and a current-generation publish returns false with an empty snapshot

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::closes PiP and clears on null auth_user_id alone, then refuses a current-generation publish

#### Scenario: Real Schedule Logout under Host
- **WHEN** the real Schedule page under FocusIndicatorHost transitions to Login with a null user and unmounts
- **THEN** the PiP closes and retained blocks and categories are empty

Tests: frontend/tests/scheduleFocusIndicatorLogoutPrivacy.test.ts::Schedule under FocusIndicatorHost logout privacy (#212)::clears retained blocks and categories when real Schedule unmounts after Login
