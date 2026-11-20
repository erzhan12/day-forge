# 0105 — Sources rail redesign: review

## Local staged review (review-fix-loop-staged)

One iteration, five parallel reviewers (quality, security, performance, testing, documentation). No critical findings.

Fixed from the warnings:

- `prefers-reduced-motion` did not stop the leave fade: the reduced-motion rule had lower specificity than the `:has(.df-checkbox:checked)` rule. It now uses the same selector.
- A panel test triggered `change` on a disabled input, which Vue Test Utils skips, so it proved nothing. It now asserts the disabled state directly.
- A stale date-format comment.

Rejected: "classic and light_premium lack `--provider-*` and `--checkbox-border` overrides". The `:root` values are the light-theme values; only the dark themes (`strategic`, `dark_4a`) override them.

## External review trail (ext-code-review)

Engines: Codex (per aspect) and Cursor (whole diff). Base `5dc0aaf`.

| Round | Runs | Valid P1/P2 | Fixed |
|---|---|---|---|
| 1 | Codex × 5 aspects, Cursor × 1 | 5 | 5 |
| 2 | Codex testing, docs, whole; Cursor × 1 | 4 | 4 |
| 3 | Codex testing, quality, whole; Cursor × 1 | 0 in code | — |

Round 1 fixes:

- The Habitica leave test now checks the box first, and there is a Habitica rollback test (restored row is a fresh, unchecked control).
- Both leave tests assert the `df-task-leave-active` class, tying the `TransitionGroup` name to the stylesheet; the stylesheet test also pins the reduced-motion override.
- Calendar summary tests cover timed events on past and future viewed dates.
- `calendarColor` tests pin distinct hues for known names.
- The plan now states that an unavailable-source suffix takes precedence over the loading suffix, as the code does.

Round 2 fixes:

- Forced-colors mode drops box-shadow focus rings. `.df-checkbox`, the rail section headers and the rail icon buttons now get an outline there.
- An expanded, embedded calendar with no events had no live loading announcement. The embedded skeleton is now `role="status"` with a label.
- Calendar tests cover `Now` and `Next` in a non-UTC zone across midnight, and an unavailable source while another is still loading.
- The stylesheet test checks the strike-through and fade declarations, not only the selectors.
- The rail time column no longer wraps "All day".

Round 3 raised one process item, not a code defect: light themes were checked through resolved tokens, not in a browser. It is on the manual checklist below.

Accepted P3 gaps:

- Leave tests stop at the leaving state; jsdom runs no transitions, so final removal is not asserted.
- The bar fill width is asserted only at 0 %.
- Embedded rows assert the source line, not the time column or the stripe variable.
- Re-expanding a section is not asserted to drop `inert`.
- Setting `process.env.TZ` at runtime may not change Intl's zone; `formatShortCivilDate` is correct by construction (`timeZone: "UTC"`).

Verification after the last fix: `make check` (2855 backend, 1587 Vitest, OpenSpec strict and anchors) and `make frontend-build` pass.

## Manual checklist

- Calendar rows in the rail with real events: time column, stripe, source, `+ Add to schedule`, collapsed `Now`/`Next` peek.
- A light theme: classic sidebar task checkboxes and block checkboxes (unchecked, checked, disabled, keyboard focus).
- Completing a real task: strike-through and fade, then the counter moves.
