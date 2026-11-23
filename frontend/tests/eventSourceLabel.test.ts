import { describe, expect, it } from "vitest"
import { eventSourceLabel } from "../src/utils/eventSourceLabel"
import type { NormalizedEvent } from "../src/types/calendar"

function ev(overrides: Partial<NormalizedEvent> = {}): NormalizedEvent {
  return {
    title: "Standup",
    start: "2026-11-22T14:00:00Z",
    end: "2026-11-22T15:00:00Z",
    calendar_name: "Work",
    all_day: false,
    external_uid: "uid",
    account_label: "alice@gmail.com",
    ...overrides,
  }
}

describe("eventSourceLabel (0106)", () => {
  it("uses the calendar name (Work · 1h)", () => {
    expect(eventSourceLabel(ev())).toBe("Work · 1h")
  })

  it("falls back to the account label when the name is empty", () => {
    expect(eventSourceLabel(ev({ calendar_name: "  ", account_label: "Family" }))).toBe("Family · 1h")
  })

  it("shows the local part when the name is an email", () => {
    expect(eventSourceLabel(ev({ calendar_name: "alice.smith@gmail.com" }))).toBe("alice.smith · 1h")
    expect(eventSourceLabel(ev({ calendar_name: "", account_label: "bob@example.org" }))).toBe("bob · 1h")
  })

  it("never invents Personal", () => {
    expect(eventSourceLabel(ev({ calendar_name: "", account_label: "" }))).not.toContain("Personal")
  })

  it("formats 30m and 1h 30m", () => {
    expect(eventSourceLabel(ev({ end: "2026-11-22T14:30:00Z" }))).toBe("Work · 30m")
    expect(eventSourceLabel(ev({ end: "2026-11-22T15:30:00Z" }))).toBe("Work · 1h 30m")
  })

  it("omits the duration for all-day and zero-length events", () => {
    expect(eventSourceLabel(ev({ all_day: true }))).toBe("Work")
    expect(eventSourceLabel(ev({ end: "2026-11-22T14:00:00Z" }))).toBe("Work")
  })

  it("returns the duration alone when no name exists", () => {
    expect(eventSourceLabel(ev({ calendar_name: "", account_label: "" }))).toBe("1h")
  })
})
