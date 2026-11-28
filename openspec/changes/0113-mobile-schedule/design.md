# 0113 design pointers

The design lives in [docs/features/0113_PLAN.md](../../../docs/features/0113_PLAN.md). Requirements for behavior that a later stage delivers carry no `Enforced:` or `Tests:` line yet (the anchor checker would reject invented anchors); the stage that lands the behavior adds them.

## Stage 2 choices

- **Calendars.** The calendar panel stays wired in `Schedule.vue` and is rendered inside `MobileCalendarsSheet` when the gear menu's Calendars item is chosen. The placement below 1024 px is already forced to `center` (`narrow4aCalendar`), so `useExternalSources` keeps polling while the page is mounted; gating polling on the sheet being open would touch `externalPollActive` and is deferred. The menu item only shows when a calendar is connected.
- **Add to schedule** closes the sheet before the existing dialog opens.
- **View analytics** keeps the desktop condition (date not in the future, schedule not a draft).
- **Interim Undo.** The header has no Undo button; until stage 5 mobile has only the keyboard shortcut. Stage 5 adds the toast.
- **Header and safe area.** The header is sticky, cancels the body's top safe-area padding with a negative margin and paints the inset with its own padding.
- **Dialog behavior** (focus in, Tab wrap, Escape, focus return) lives in `useMobileDialog` and is reused by the sheets of stage 4.

## Stage 3 choices

- **Reuse, not rewrite.** `MobileBlockRow` wraps `TimeBlock.vue` with a new `mobile` prop (as `TimeBlock4a` wraps it with `density`). Completion queue, optimistic checkbox, inline title edit, long-press tooltip and delete keep one implementation; the prop only changes what the SPEC changes (× deletes at once, grip inert and `aria-hidden`, no end time or countdown, error floats because the row is a fixed 52 px).
- **Rows come from the base builder** with the whole window as render range and no clock (`buildMobileRows`), so nothing is scaled, edge gaps are whole and the trailing gap is not split at "now". Inert spacers are dropped.
- **Undo.** Mobile delete registers the same silent Undo entry as desktop; the keyboard shortcut works. The visible toast is stage 5.
- **Mockup vs rule.** SPEC 11.3 gives every gap its own row, but the mockup day omits the 5-minute gap between Lunch and Kick-off and the 10-minute gap before My VC Course. The rule wins: the sketch day renders 10 rows, not 8. Ask the designer whether gaps under 15 minutes may fold into a thinner row.
- **«8 rows on 375×667».** Space between the 56 px header and the 52 px chat bar is about 559 px at 667 px height. The mockup's 8 rows (5 blocks, 3 gaps) take 472 px and fit; the 10 rows the gap rule produces for the same day take 584 px and overflow by about 25 px, so that day scrolls slightly on a 375×667 phone (it fits at 390×844, 736 px). Spec heights are kept; the criterion needs the designer's call together with the gap-folding question above.
- **Overlapping blocks** simply list in start order with no gap row between them.

