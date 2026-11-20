import { describe, expect, it } from "vitest"
import { CALENDAR_HUE_COUNT, calendarColorVar, calendarHueIndex } from "../src/utils/calendarColor"

describe("calendarColor", () => {
  it("is deterministic for the same calendar name", () => {
    expect(calendarColorVar("Work")).toBe(calendarColorVar("Work"))
  })

  it("stays inside the palette for many names", () => {
    for (let i = 0; i < 500; i++) {
      const index = calendarHueIndex(`calendar-${i}-${"x".repeat(i % 7)}`)
      expect(index).toBeGreaterThanOrEqual(0)
      expect(index).toBeLessThan(CALENDAR_HUE_COUNT)
    }
  })

  it("spreads different calendar names across the palette", () => {
    expect(calendarHueIndex("Team")).toBe(0)
    expect(calendarHueIndex("Family")).toBe(1)
    expect(calendarHueIndex("Home")).toBe(2)
    expect(calendarHueIndex("Personal")).toBe(3)
    expect(calendarHueIndex("Work")).toBe(4)
  })

  it("maps an empty name to the first hue", () => {
    expect(calendarColorVar("")).toBe("var(--calendar-hue-1)")
  })
})
