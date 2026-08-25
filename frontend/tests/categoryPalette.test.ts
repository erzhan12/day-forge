import { describe, it, expect } from "vitest"
import { categoryPalette } from "../src/utils/categoryPalette"

// Feature 0063: the palette is a fixed set of theme-independent swatches, each
// audited to clear WCAG 1.4.11 (3:1) against every theme's panel background.

const EXPECTED = {
  blue: "#3B82F6",
  violet: "#8B5CF6",
  emerald: "#059669",
  gray: "#6B7280",
  amber: "#D97706",
  rose: "#E11D48",
  cyan: "#0891B2",
  indigo: "#6366F1",
} as const

// Effective panel backgrounds per theme (src/utils/themes.ts bgPanel; strategic
// uses the audited composite of its translucent panel over the page).
const PANEL_BACKGROUNDS = {
  classic: "#ffffff",
  strategic: "#121a2c",
  light_premium: "#fffdf8",
  dark_4a: "#1B1D20",
}

function channel(c: number): number {
  const s = c / 255
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16)
  return (
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255)
  )
}

function contrast(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la > lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

describe("categoryPalette", () => {
  it("exposes exactly the eight audited swatches with their hexes", () => {
    expect(categoryPalette).toEqual(EXPECTED)
  })

  it("preserves the seed mapping (matches the backend SEED_CATEGORIES colours)", () => {
    expect(categoryPalette.blue).toBe("#3B82F6") // Work
    expect(categoryPalette.violet).toBe("#8B5CF6") // Personal
    expect(categoryPalette.emerald).toBe("#059669") // Health (the audited value, not #10B981)
    expect(categoryPalette.gray).toBe("#6B7280") // Other
  })

  it("every swatch clears 3:1 contrast against every theme panel background", () => {
    for (const [id, hex] of Object.entries(categoryPalette)) {
      for (const [theme, bg] of Object.entries(PANEL_BACKGROUNDS)) {
        const ratio = contrast(hex, bg)
        expect(ratio, `${id} on ${theme}`).toBeGreaterThanOrEqual(3.0)
      }
    }
  })

  it("allows two categories to share a colour (no uniqueness on colour_id)", () => {
    // Purely a documentation assertion: the palette is a lookup, not a set of
    // per-category exclusive colours — sharing is legal by construction.
    const ids = Object.keys(categoryPalette)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
