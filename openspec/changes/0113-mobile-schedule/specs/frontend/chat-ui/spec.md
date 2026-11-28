## ADDED Requirements

### Requirement: Mobile privacy hint sits behind the info control
At 640 px and below in Dark 4a the chat panel SHALL hide the full privacy text in rest state behind an ⓘ control that opens it, SHALL show a one-line short form while the field is focused, and SHALL never remove the hint. Desktop and the tablet dock SHALL keep the hint visible before the first keystroke.
Enforced: frontend/src/components/CommandBar.vue::chat-privacy-hint-short, frontend/scripts/playwright/ai-chat-privacy-hint-always-on.mjs::State E

#### Scenario: Rest state
- **WHEN** the mobile panel is idle
- **THEN** ⓘ opens the full privacy text and no hint line is shown

Tests: frontend/tests/CommandBar.test.ts::CommandBar on the phone (feature 0113)::opens the full privacy text in a sheet behind ⓘ and closes it, frontend/tests/CommandBar.test.ts::CommandBar on the phone (feature 0113)::leaves the desktop dock unchanged without the mobile prop

#### Scenario: Focused field
- **WHEN** the mobile field is focused
- **THEN** a one-line `Messages may be sent to the AI provider.` appears above it

Tests: frontend/tests/CommandBar.test.ts::CommandBar on the phone (feature 0113)::shows the chips and the one-line disclaimer only while the field is focused

### Requirement: Mobile chat panel
At 640 px and below in Dark 4a the chat dock SHALL rest as one 52 px row (ⓘ, a 16 px field, a 36 px send button muted and `aria-disabled` while empty), show a row of 32 px chips only while the field is focused, ride above the keyboard, and keep an open AI question visible at rest.
Enforced: frontend/src/components/CommandBar.vue::command-bar--mobile, frontend/src/components/ChatResultChip.vue::chat-result-chip--mobile, frontend/src/pages/Schedule.vue::mobileLayout

#### Scenario: Rest and send
- **WHEN** the panel is idle and text is typed
- **THEN** only the row shows and send turns coral and submits through the normal path

Tests: frontend/tests/CommandBar.test.ts::CommandBar on the phone (feature 0113)::rests as one row: no hint, chips or thread; ⓘ, field and a muted send, frontend/tests/CommandBar.test.ts::CommandBar on the phone (feature 0113)::enables send only with text and submits through the same path, frontend/tests/CommandBar.test.ts::CommandBar on the phone (feature 0113)::keeps an open AI question visible at rest, and Clear while focused

#### Scenario: Chip tap keeps the row
- **WHEN** a chip is tapped while the field is focused
- **THEN** the pointer-down is cancelled so focus stays, and the chip text is sent

Tests: frontend/tests/CommandBar.test.ts::CommandBar on the phone (feature 0113)::keeps the row while focus moves to a chip, and sends the chip text, frontend/tests/Schedule.test.ts::Schedule.vue Dark 4a mobile header (0113)::gives the phone the one-row chat dock and keeps the other layouts on the old dock
