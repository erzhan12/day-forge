## ADDED Requirements

### Requirement: Mobile delete is immediate with an Undo toast
At 640 px and below in Dark 4a, tapping a block's × SHALL delete it without `DeleteConfirmationDialog` and show a `Block deleted · Undo` toast for 5 seconds; Undo SHALL restore the block through the normal Undo entry. Wider screens and category deletion SHALL keep the confirmation dialog.

#### Scenario: Delete on mobile
- **WHEN** × is tapped on a mobile block row
- **THEN** the block is deleted at once and the toast offers Undo for 5 seconds

#### Scenario: Delete on desktop
- **WHEN** × is tapped above 640 px
- **THEN** the confirmation dialog opens first
