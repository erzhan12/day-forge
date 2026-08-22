import { describe, expect, it } from "vitest"
import { isKnownTheme } from "../src/utils/theme"
import { THEMES } from "../src/utils/themes"

describe("dark_4a registration", () => {
  it("is known and has a complete selector definition", () => {
    expect(isKnownTheme("dark_4a")).toBe(true)
    const design = THEMES.find((theme) => theme.id === "dark_4a")
    expect(design).toBeDefined()
    expect(design?.preview.bgPage).toBe("#17181A")
    expect(design?.preview.bgPanel).toBe("#1B1D20")
    expect(design?.preview.accent).toBe("oklch(0.72 0.17 30)")
    expect(design?.preview.textPrimary).toBe("#ECEAE6")
    expect(THEMES).toHaveLength(4)
  })
})
