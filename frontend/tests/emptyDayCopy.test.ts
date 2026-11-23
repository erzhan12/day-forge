import { describe, expect, it } from "vitest"
import { emptyDayCopy } from "../src/utils/emptyDayCopy"
import { weekdayName } from "../src/utils/date"

describe("emptyDayCopy (0106)", () => {
  it("names the weekday of the selected date in English", () => {
    const week: Array<[string, string]> = [
      ["2026-11-16", "Monday"], ["2026-11-17", "Tuesday"], ["2026-11-18", "Wednesday"],
      ["2026-11-19", "Thursday"], ["2026-11-20", "Friday"], ["2026-11-21", "Saturday"],
      ["2026-11-22", "Sunday"],
    ]
    for (const [date, name] of week) {
      expect(weekdayName(date)).toBe(name)
      expect(emptyDayCopy(date, "weekday").title).toBe(`No template for ${name}`)
    }
  })

  it.each(["Pacific/Honolulu", "Pacific/Kiritimati"])("does not shift the weekday at UTC−10 or UTC+14 (%s)", (zone) => {
    const previous = process.env.TZ
    process.env.TZ = zone
    try {
      expect(weekdayName("2026-11-22")).toBe("Sunday")
      expect(weekdayName("2026-11-23")).toBe("Monday")
    } finally {
      if (previous === undefined) delete process.env.TZ
      else process.env.TZ = previous
    }
  })

  it("offers Create weekend template on Saturday and Sunday", () => {
    expect(emptyDayCopy("2026-11-21", "weekend").primaryLabel).toBe("Create weekend template")
    expect(emptyDayCopy("2026-11-22", "weekend").primaryLabel).toBe("Create weekend template")
  })

  it("offers Create weekday template on Monday to Friday", () => {
    for (const date of ["2026-11-16", "2026-11-18", "2026-11-20"]) {
      expect(emptyDayCopy(date, "weekday").primaryLabel).toBe("Create weekday template")
    }
  })
})
