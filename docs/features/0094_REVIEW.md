# 0094 Single-row TimeBlock cards: review

Every TimeBlock card and the drag ghost now use one row: checkbox, time range, duration, optional countdown, title, delete. The 30-minute compact threshold and `ghostIsCompact` are gone.

## Local staged review

No criticals. Non-blocking notes:

- `Schedule.vue`: the drag ghost has no duration span, so its title starts a little left of the real card's title.
- `Schedule.vue`: the ghost CSS repeats the row metrics of `TimeBlock.vue` by hand. A row change must update both.

## External review trail

Engine: Codex, run per aspect (quality, security, performance, testing, docs). Cursor was dropped because the CLI was not logged in.

| Round | Finding | Verdict |
|---|---|---|
| 1 | P1 quality: at 320px the badges leave no width for the title on a current 90-minute block | Accepted. The title keeps 48px, the countdown can shrink, and below 300px card width the duration is hidden; on the current block the time range is hidden too |
| 1 | P2 testing: the single-row test checks only DOM structure | Accepted as a gap. jsdom cannot evaluate container queries or flex widths. Checked by hand in a browser at 320px and on desktop |
| 1 | P2 testing: the drag ghost had no rendering test | Accepted. `Schedule.test.ts` renders the ghost for short and long blocks |
| 2 | P2 testing: the `clampedDragDuration` mock always returned 30 minutes | Accepted. The mock now returns the real block length |
| 3 | none | — |

Final verification: `make check` passed (2674 backend tests, 1528 frontend tests); `make frontend-build` passed.
