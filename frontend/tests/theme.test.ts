import { describe, it, expect, beforeEach } from "vitest"
import { applyTheme, isKnownTheme, normalizeTheme } from "../src/utils/theme"

describe("isKnownTheme", () => {
  it.each(["classic", "strategic", "light_premium"] as const)(
    "returns true for known theme %s",
    (id) => {
      expect(isKnownTheme(id)).toBe(true)
    },
  )

  it.each([undefined, null, "", "unknown", "CLASSIC", 42, {}])(
    "returns false for invalid input %p",
    (raw) => {
      expect(isKnownTheme(raw)).toBe(false)
    },
  )
})

describe("normalizeTheme", () => {
  it("returns recognized values unchanged", () => {
    expect(normalizeTheme("classic")).toBe("classic")
    expect(normalizeTheme("strategic")).toBe("strategic")
    expect(normalizeTheme("light_premium")).toBe("light_premium")
  })

  it("maps invalid/missing values to classic", () => {
    expect(normalizeTheme(undefined)).toBe("classic")
    expect(normalizeTheme(null)).toBe("classic")
    expect(normalizeTheme("")).toBe("classic")
    expect(normalizeTheme("neon")).toBe("classic")
    expect(normalizeTheme(123)).toBe("classic")
  })
})

describe("applyTheme", () => {
  beforeEach(() => {
    delete document.documentElement.dataset.theme
  })

  it("sets dataset.theme on <html>", () => {
    applyTheme("strategic")
    expect(document.documentElement.dataset.theme).toBe("strategic")
    applyTheme("light_premium")
    expect(document.documentElement.dataset.theme).toBe("light_premium")
  })

  it("does not normalize internally (caller's responsibility)", () => {
    // applyTheme accepts only ThemeId at the type level. At runtime we
    // verify it writes the raw value, never coerces to 'classic'.
    applyTheme("strategic")
    expect(document.documentElement.dataset.theme).toBe("strategic")
  })
})
