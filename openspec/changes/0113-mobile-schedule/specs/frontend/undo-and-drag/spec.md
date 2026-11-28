## ADDED Requirements

### Requirement: Mobile delete is immediate
At 640 px and below in Dark 4a, tapping a block's × SHALL delete it without `DeleteConfirmationDialog` and register the normal Undo entry. Wider screens and category deletion SHALL keep the confirmation dialog.
Enforced: frontend/src/components/TimeBlock.vue::onDeleteClick

#### Scenario: Delete on mobile
- **WHEN** × is tapped on a mobile block row
- **THEN** the block is deleted at once and an Undo entry is pushed

Tests: frontend/tests/MobileList.test.ts::TimelineMobile (feature 0113)::deletes on the × tap without a confirmation dialog and registers Undo

#### Scenario: Delete on desktop
- **WHEN** × is tapped above 640 px
- **THEN** the confirmation dialog opens first

Tests: frontend/tests/TimeBlock.test.ts::TimeBlock::calls delete after confirm

### Requirement: Mobile Undo toast
On mobile a delete, move or add SHALL show a single `Block deleted · Undo`, `Block moved · Undo` or `Block added · Undo` toast for 5 seconds, replacing any earlier toast; Undo SHALL restore through the normal Undo entry.

#### Scenario: Toast
- **WHEN** a mobile delete succeeds
- **THEN** the toast offers Undo for 5 seconds
