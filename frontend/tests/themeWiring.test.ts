import { describe, it, expect } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

// Static-scan wiring test: every authenticated page MUST call
// useThemeFromProps() in its setup block. Failing this test means a
// partial Inertia reload (e.g. router.reload({ only: ["something_else"] }))
// would not propagate ui_preferences changes to <html data-theme>.
//
// If you add a new authenticated Inertia page, add its file path here.
// The rule is documented in RULES.md.

const AUTHENTICATED_PAGES = [
  "src/pages/Schedule.vue",
  "src/pages/Settings.vue",
  "src/pages/Analytics.vue",
]

describe("authenticated pages call useThemeFromProps()", () => {
  it.each(AUTHENTICATED_PAGES)("%s", (page) => {
    const path = resolve(__dirname, "..", page)
    const source = readFileSync(path, "utf-8")
    expect(source).toContain("useThemeFromProps(")
  })
})
