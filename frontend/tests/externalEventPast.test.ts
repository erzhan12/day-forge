import { describe, expect, it } from "vitest"
import { isExternalEventPast } from "../src/utils/externalEventPast"
import type { NormalizedEvent } from "../src/types/calendar"

const timed = (start: string, end: string): NormalizedEvent => ({
  title: "Meet",
  start,
  end,
  calendar_name: "Work",
  all_day: false,
  external_uid: "uid-1",
  account_label: "",
})

const allDay: NormalizedEvent = {
  title: "Holiday",
  start: "2026-05-07T00:00:00",
  end: "2026-05-08T00:00:00",
  calendar_name: "Personal",
  all_day: true,
  external_uid: "uid-2",
  account_label: "",
}

describe("isExternalEventPast", () => {
  const today = "2026-05-07"

  it("marks timed events ended at or before nowMinutes on today", () => {
    const ended = timed("2026-05-07T14:00:00", "2026-05-07T15:00:00")
    const ongoing = timed("2026-05-07T16:00:00", "2026-05-07T17:00:00")
    const nowMinutes = 16 * 60
    expect(isExternalEventPast(ended, today, today, nowMinutes)).toBe(true)
    expect(isExternalEventPast(ongoing, today, today, nowMinutes)).toBe(false)
  })

  it("leaves all-day events full strength on today", () => {
    expect(isExternalEventPast(allDay, today, today, 16 * 60)).toBe(false)
  })

  it("dims every event on a past viewed date", () => {
    const ev = timed("2026-05-06T10:00:00", "2026-05-06T11:00:00")
    expect(isExternalEventPast(ev, "2026-05-06", today, null)).toBe(true)
  })

  it("dims nothing on a future viewed date", () => {
    const ev = timed("2026-05-08T10:00:00", "2026-05-08T11:00:00")
    expect(isExternalEventPast(ev, "2026-05-08", today, null)).toBe(false)
  })
})
