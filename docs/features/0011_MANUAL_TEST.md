---
name: 0011 - Apple Calendar (CalDAV) manual test plan
description: Browser smoke checklist for the CalDAV connect flow, event display, and degraded paths.
type: manual-test
---

# 0011 - Apple Calendar (CalDAV) manual test plan

Run after every change to `calendar_sync/`, `frontend/src/composables/useCalendar.ts`,
`frontend/src/composables/useCalendarAccount.ts`, `ExternalEventsPanel.vue`,
or the related sections of `Settings.vue` / `Schedule.vue`.

## Prerequisites

- `CALDAV_ENCRYPTION_KEY` set in `.env` to a valid Fernet key — generate
  with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- An Apple ID with an [app-specific password](https://support.apple.com/en-us/HT204397).
- Backend + Vite both running (see `.claude/rules/workflows.md`).

## Test cases

### TC-01 — Settings: connect (happy path)
- [ ] Visit `/settings/`.
- [ ] In "Apple Calendar" section, status reads "Not connected".
- [ ] Enter Apple ID + app-specific password, click Connect.
- [ ] Button shows "Connecting…" then settles; status flips to
      "Connected as <apple-id>".
- [ ] Reload the page; connection persists (status fetched from server).
- [ ] Password field is empty after reload (never pre-populated).

### TC-02 — Settings: disconnect
- [ ] With an account connected, click Disconnect.
- [ ] Button shows "Disconnecting…" then settles; status flips to
      "Not connected".
- [ ] Reload the page; status remains "Not connected".

### TC-03 — Settings: connect with bad credentials
- [ ] Enter Apple ID + an obviously bogus password.
- [ ] Click Connect.
- [ ] Status remains "Not connected" and an inline error message reads
      "Invalid Apple Calendar credentials".
- [ ] No `CalDAVAccount` row was created (verify via `python backend/manage.py
      shell` → `CalDAVAccount.objects.filter(user__username=...).exists()`).

### TC-04 — Settings: advanced base URL
- [ ] Click "Show advanced". The CalDAV base URL field appears with the
      default URL as placeholder.
- [ ] Connect with the field blank — should succeed (uses default).
- [ ] Disconnect; reconnect with a custom URL field value — should
      succeed and persist.

### TC-05 — Settings: serialisation lock
- [ ] With a slow network (DevTools → throttle to "Slow 3G"), click
      Connect, then immediately click Connect or Disconnect again.
- [ ] The second click is rejected with the message "Another account
      operation is in progress. Please wait." (no double-network-call).

### TC-06 — Schedule page: events display
- [ ] With an account connected, navigate to `/schedule/<today>/`.
- [ ] The "Apple Calendar" panel renders above the time-block list.
- [ ] Today's calendar events appear (timed events show start-end range,
      all-day events show "All day").
- [ ] Each row shows the calendar name as a chip.
- [ ] Events are read-only — no edit / delete / completion checkbox.

### TC-07 — Schedule page: navigation between dates
- [ ] Use the date navigator to move forward / back several days.
- [ ] Each day's events render correctly; rapid clicks do NOT cause a
      previous day's events to "stick" on a later day.

### TC-08 — Schedule page: empty day
- [ ] Navigate to a date with no Apple Calendar events.
- [ ] Panel shows "No Apple Calendar events for this day."

### TC-09 — Schedule page: 401 surface (credentials revoked)
- [ ] Rotate/revoke the app-specific password in Apple ID settings,
      then revisit the Schedule page (do NOT reconnect in Day Forge).
- [ ] Panel shows the message "Apple Calendar credentials invalid.
      Reconnect in Settings." with a Retry button.

### TC-10 — Schedule page: network failure
- [ ] DevTools → "Offline" mode; reload the Schedule page.
- [ ] Panel shows "Apple Calendar service unavailable" (502/504 path).
- [ ] Retry button is functional after going back online.

### TC-11 — Schedule page: not connected
- [ ] Disconnect the account in Settings, then navigate to the Schedule
      page.
- [ ] The "Apple Calendar" panel is hidden entirely (no empty panel,
      no stub row).

### TC-12 — Cache invalidation on credential rotation
- [ ] With an account connected and events visible, change the
      password in Settings (Disconnect → Connect with new password).
- [ ] Revisit Schedule. Events re-fetch from iCloud (verify by
      tailing `backend/manage.py runserver` log — a fresh GET to
      `/api/calendar/events/<date>/` hits the DAVClient).
