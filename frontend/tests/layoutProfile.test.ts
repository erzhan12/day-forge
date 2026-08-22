import { describe, expect, it } from "vitest"
import { layoutForTheme, pxPerMinuteForLayout } from "../src/utils/layoutProfile"

describe("layout profiles", () => {
  it("maps only dark_4a to the alternate layout", () => {
    expect(layoutForTheme("dark_4a")).toBe("4a")
    expect(layoutForTheme("classic")).toBe("classic")
    expect(layoutForTheme("strategic")).toBe("classic")
    expect(layoutForTheme("light_premium")).toBe("classic")
  })

  it("uses the design-specific time scale", () => {
    expect(pxPerMinuteForLayout("4a")).toBe(1.6)
    expect(pxPerMinuteForLayout("classic")).toBe(2)
  })
})
