## ADDED Requirements

### Requirement: Mobile privacy hint sits behind the info control
At 640 px and below in Dark 4a the chat panel SHALL hide the full privacy text in rest state behind an ⓘ control that opens it, SHALL show a one-line short form while the field is focused, and SHALL never remove the hint. Desktop and the tablet dock SHALL keep the hint visible before the first keystroke.

#### Scenario: Rest state
- **WHEN** the mobile panel is idle
- **THEN** ⓘ opens the full privacy text and no hint line is shown

#### Scenario: Focused field
- **WHEN** the mobile field is focused
- **THEN** a one-line `Messages may be sent to the AI provider.` appears above it
