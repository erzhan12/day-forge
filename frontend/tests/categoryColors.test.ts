import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import {
  categoryColors,
  getCategoryColor,
} from "../src/utils/categoryColors"

describe("getCategoryColor (theme overrides)", () => {
  beforeEach(() => {
    delete document.documentElement.dataset.theme
  })

  afterEach(() => {
    delete document.documentElement.dataset.theme
  })

  it("returns the base palette when no override exists for the theme", () => {
    expect(getCategoryColor("work", "classic")).toBe(categoryColors.work)
    expect(getCategoryColor("personal", "strategic")).toBe(
      categoryColors.personal,
    )
    expect(getCategoryColor("other", "light_premium")).toBe(
      categoryColors.other,
    )
  })

  it("applies the health override on Classic (WCAG 3:1 fix)", () => {
    expect(getCategoryColor("health", "classic")).toBe("#059669")
    // Sanity: base value is the failing one — proves the override path
    // is what produces the post-fix value.
    expect(categoryColors.health).toBe("#10B981")
  })

  it("applies the health override on Light Premium (WCAG 3:1 fix)", () => {
    expect(getCategoryColor("health", "light_premium")).toBe("#059669")
  })

  it("does NOT override health on Strategic (base passes 3:1 vs dark panel)", () => {
    expect(getCategoryColor("health", "strategic")).toBe(categoryColors.health)
  })

  it("resolves theme from <html data-theme> when none is passed", () => {
    document.documentElement.dataset.theme = "classic"
    expect(getCategoryColor("health")).toBe("#059669")
    document.documentElement.dataset.theme = "strategic"
    expect(getCategoryColor("health")).toBe(categoryColors.health)
  })

  it("falls back to classic when dataset.theme is missing/invalid", () => {
    // Absent
    expect(getCategoryColor("health")).toBe("#059669") // Classic override
    document.documentElement.dataset.theme = "garbage"
    expect(getCategoryColor("health")).toBe("#059669")
  })
})

// Static scan: prove the rendering components actually call the themed
// getter, not the raw `categoryColors` map. Without this, a future
// regression where someone reverts to `categoryColors[...]` would silently
// re-introduce the WCAG failure without breaking any unit test.
describe("components route through getCategoryColor()", () => {
  const PAGES = [
    "src/components/TimeBlock.vue",
    "src/components/CategoryBreakdown.vue",
    "src/components/SkippedTasks.vue",
  ]

  it.each(PAGES)("%s imports getCategoryColor and not the raw map", (path) => {
    const source = readFileSync(resolve(__dirname, "..", path), "utf-8")
    expect(source).toContain("getCategoryColor")
    // The raw map import must NOT appear — `categoryColors` substring
    // would also match a comment or test reference, so check the import
    // line specifically.
    expect(source).not.toMatch(
      /import\s*\{[^}]*\bcategoryColors\b[^}]*\}\s*from\s*["']\.\.\/utils\/categoryColors["']/,
    )
  })
})
