import { describe, expect, it } from "vitest"
import { addCivilDays, civilDayDelta, formatCivilDate, formatMobileHeaderDate, formatShortCivilDate, todayString, zonedDateTime } from "../src/utils/date"

describe("saved-zone civil time", () => {
  it.each([
    ["UTC", "2026-10-10T23:30:00Z", "2026-10-10", "23:30"],
    ["Asia/Qatar", "2026-10-10T23:30:00Z", "2026-10-11", "02:30"],
    ["America/Los_Angeles", "2026-10-10T02:30:00Z", "2026-10-09", "19:30"],
    ["Asia/Kathmandu", "2026-10-10T19:00:00Z", "2026-10-11", "00:45"],
    ["America/New_York", "2026-03-08T06:59:00Z", "2026-03-08", "01:59"],
    ["America/New_York", "2026-03-08T07:00:00Z", "2026-03-08", "03:00"],
    ["America/New_York", "2026-11-01T05:30:00Z", "2026-11-01", "01:30"],
    ["America/New_York", "2026-11-01T06:30:00Z", "2026-11-01", "01:30"],
  ])("maps %s at %s to %s %s", (zone, iso, date, hhmm) => {
    const instant = new Date(iso)
    const sample = zonedDateTime(instant, zone)
    expect(sample).toMatchObject({ date, hhmm })
    expect(sample.minutes).toBe(sample.hours * 60 + sample.minute)
    expect(todayString(zone, instant)).toBe(date)
  })

  it("falls back to UTC for a corrupt saved timezone", () => {
    expect(zonedDateTime(new Date("2026-10-10T23:30:00Z"), "Mars/Olympus"))
      .toMatchObject({ date: "2026-10-10", hhmm: "23:30", minutes: 1410 })
  })

  it("moves civil dates independently of DST and host timezone", () => {
    expect(addCivilDays("2026-03-08", 1)).toBe("2026-03-09")
    expect(addCivilDays("2026-11-01", -1)).toBe("2026-10-31")
    expect(civilDayDelta("2026-03-08", "2026-03-09")).toBe(1)
    expect(civilDayDelta("2026-11-02", "2026-11-01")).toBe(-1)
    expect(formatCivilDate("2026-03-08")).toBe("Sunday, March 8, 2026")
  })
})

describe("formatShortCivilDate", () => {
  it.each(["Pacific/Honolulu", "Pacific/Kiritimati", "UTC"])("keeps the civil weekday with the process TZ at %s", (zone) => {
    const previous = process.env.TZ
    process.env.TZ = zone
    try {
      expect(formatShortCivilDate("2026-11-19")).toBe("Thu 19 Nov")
      expect(formatShortCivilDate("2027-01-01")).toBe("Fri 1 Jan")
    } finally {
      if (previous === undefined) delete process.env.TZ
      else process.env.TZ = previous
    }
  })
})

describe("formatMobileHeaderDate (feature 0113)", () => {
  it.each([
    ["2026-11-27", "Fri, Nov 27"],
    ["2026-03-08", "Sun, Mar 8"],
    ["2026-12-31", "Thu, Dec 31"],
  ])("formats %s as %s without year or full weekday", (date, expected) => {
    expect(formatMobileHeaderDate(date)).toBe(expected)
  })
})
