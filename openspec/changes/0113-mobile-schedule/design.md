# 0113 design pointers

The design lives in [docs/features/0113_PLAN.md](../../../docs/features/0113_PLAN.md). Requirements for behavior that a later stage delivers carry no `Enforced:` or `Tests:` line yet (the anchor checker would reject invented anchors); the stage that lands the behavior adds them.

## Stage 2 choices

- **Calendars.** The calendar panel stays wired in `Schedule.vue` and is rendered inside `MobileCalendarsSheet` when the gear menu's Calendars item is chosen. The placement below 1024 px is already forced to `center` (`narrow4aCalendar`), so `useExternalSources` keeps polling while the page is mounted; gating polling on the sheet being open would touch `externalPollActive` and is deferred. The menu item only shows when a calendar is connected.
- **Add to schedule** closes the sheet before the existing dialog opens.
- **View analytics** keeps the desktop condition (date not in the future, schedule not a draft).
- **Interim Undo.** The header has no Undo button; until stage 5 mobile has only the keyboard shortcut. Stage 5 adds the toast.
- **Header and safe area.** The header is sticky, cancels the body's top safe-area padding with a negative margin and paints the inset with its own padding.
- **Dialog behavior** (focus in, Tab wrap, Escape, focus return) lives in `useMobileDialog` and is reused by the sheets of stage 4.

