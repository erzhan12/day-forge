## ADDED Requirements

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
