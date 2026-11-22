import { describe, expect, it } from "vitest"
import { formatGapLabel, formatGapRange } from "../src/utils/gapLabel"

describe("gapLabel (0106)", () => {
  it("formats Free · 2h 50m", () => {
    expect(formatGapLabel(170)).toBe("Free · 2h 50m")
  })

  it("formats Free · 25m and Free · 6h", () => {
    expect(formatGapLabel(25)).toBe("Free · 25m")
    expect(formatGapLabel(360)).toBe("Free · 6h")
  })

  it("formats the range as 12:10–15:00 with an en dash", () => {
    expect(formatGapRange("12:10", "15:00")).toBe("12:10–15:00")
  })
})
