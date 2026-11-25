# 0112 — calendar midnight past-state tasks

## 1. Tests
- [x] Red: ExternalEventsPanel `todayDate` rollover without remount; fallback `nowMinutes` tick across Asia/Qatar midnight; same-day `nowMinutes`
- [x] Red: Schedule stays mounted across saved-zone midnight for center and sidebar; same-day tick does not fade a later event

## 2. Fix
- [x] Re-sample `todayString(timeZone)` when `todayDate` is missing and `nowMinutes` changes (`ExternalEventsPanel`, `ExternalRail4a`)
- [x] Keep Schedule passing `todayDate` from `useNowMinutes` to every panel

## 3. Finish
- [x] Update `RULES.md`
- [x] Run `make check` and `make frontend-build`
- [x] Archive the change on the feature branch before merge
