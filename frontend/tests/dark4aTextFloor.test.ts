import { describe, expect, it } from "vitest"
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, relative, resolve } from "node:path"

// Feature 0106 text floor: in Dark 4a no text is smaller than 13 px and no
// text uses the control-border grey (#6a6e75). A static scan cannot see the
// cascade, so the binding check is the browser sweep in
// scripts/playwright/dark4a-day-fit.mjs; this test keeps the source honest:
//   - 4a-only components declare nothing below 13 px;
//   - every sub-13 px rule in a shared component has a Dark 4a-prefixed
//     rule in the same file that raises the same selector to >= 13 px.

const SRC = resolve(__dirname, "..", "src")

/** Components rendered only by the Dark 4a layout. */
const DARK_4A_ONLY = [
  "components/Timeline4a.vue",
  "components/NowLine4a.vue",
  "components/GapSlot4a.vue",
  "components/TimeBlock4a.vue",
  "components/ExternalRail4a.vue",
  "components/RailSection.vue",
  "components/EmptyDayState.vue",
  "components/BlockTooltip.vue",
  "components/settings/SettingsLogoutButton.vue",
]

/** Shared files exempt from the per-file floor, with the reason. */
const EXEMPT: Record<string, string> = {
  // Classic-only timeline pieces: Dark 4a renders GapSlot4a / NowLine4a.
  "components/GapSlot.vue": "classic timeline only",
  "components/NowLine.vue": "classic timeline only",
  // Raised from the 4a wrapper through :deep rules (TimeBlock4a.vue).
  "components/TimeBlock.vue": "covered by TimeBlock4a :deep rules",
}

/** Selectors a file may leave small because Dark 4a never renders them. */
const NOT_RENDERED_IN_4A: Record<string, string[]> = {
  // The Schedule footer is hidden in Dark 4a; the classic drag ghost is
  // replaced by the 4a ghost.
  "pages/Schedule.vue": [".logout-btn", ".ghost-time", ".ghost-duration"],
}

const DARK_4A_PREFIX = 'html[data-theme="dark_4a"]'
const SMALL_PX = /font-size:\s*(\d+(?:\.\d+)?)px|font:\s*[^;{}]*?(?<![\d.])(\d+(?:\.\d+)?)px/g

interface CssRule {
  selectors: string[]
  body: string
}

function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return vueFiles(path)
    return name.endsWith(".vue") ? [path] : []
  })
}

function styleOf(path: string): string {
  const source = readFileSync(path, "utf-8")
  return [...source.matchAll(/^<style[^>]*>([\s\S]*?)^<\/style>/gm)]
    .map((m) => m[1])
    .join("\n")
    .replace(/\/\*[\s\S]*?\*\//g, "")
}

/** Leaf rules only; @media / @container wrappers are flattened away. */
function leafRules(css: string): CssRule[] {
  const rules: CssRule[] = []
  const open = /([^{}]*)\{/g
  let match: RegExpExecArray | null
  while ((match = open.exec(css))) {
    const start = open.lastIndex
    let depth = 1
    let i = start
    while (depth > 0 && i < css.length) {
      if (css[i] === "{") depth += 1
      else if (css[i] === "}") depth -= 1
      i += 1
    }
    const body = css.slice(start, i - 1)
    if (body.includes("{")) continue
    const prelude = match[1].trim()
    if (prelude.startsWith("@")) continue
    rules.push({
      selectors: prelude.split(",").map((s) => s.replace(/\s+/g, " ").trim()).filter(Boolean),
      body,
    })
  }
  return rules
}

function smallestPx(body: string): number | null {
  let min: number | null = null
  for (const m of body.matchAll(SMALL_PX)) {
    const value = Number(m[1] ?? m[2])
    min = min === null ? value : Math.min(min, value)
  }
  return min
}

function declaredPx(body: string): number | null {
  const m = /font-size:\s*(\d+(?:\.\d+)?)px/.exec(body)
  return m ? Number(m[1]) : null
}

function rel(path: string): string {
  return relative(SRC, path).split("\\").join("/")
}

describe("Dark 4a text floor (0106)", () => {
  it("keeps every 4a-only component at 13 px or larger", () => {
    const offenders: string[] = []
    for (const file of DARK_4A_ONLY) {
      for (const rule of leafRules(styleOf(resolve(SRC, file)))) {
        const px = smallestPx(rule.body)
        if (px !== null && px < 13) offenders.push(`${file}: ${rule.selectors.join(", ")} (${px}px)`)
      }
    }
    expect(offenders).toEqual([])
  })

  it("never colours text with the control-border grey in 4a-only components", () => {
    const offenders = DARK_4A_ONLY.filter((file) =>
      /(?<![-\w])color:\s*#6a6e75/i.test(styleOf(resolve(SRC, file))),
    )
    expect(offenders).toEqual([])
  })

  it("raises every sub-13 px selector of a shared component inside Dark 4a", () => {
    const missing: string[] = []
    for (const path of vueFiles(SRC)) {
      const file = rel(path)
      if (DARK_4A_ONLY.includes(file) || file in EXEMPT) continue
      const rules = leafRules(styleOf(path))
      const floored = new Set<string>()
      for (const rule of rules) {
        const px = declaredPx(rule.body)
        if (px === null || px < 13) continue
        for (const selector of rule.selectors) {
          if (selector.startsWith(`${DARK_4A_PREFIX} `)) {
            floored.add(selector.slice(DARK_4A_PREFIX.length + 1))
          }
        }
      }
      const skipped = new Set(NOT_RENDERED_IN_4A[file] ?? [])
      for (const rule of rules) {
        const px = smallestPx(rule.body)
        if (px === null || px >= 13) continue
        for (const selector of rule.selectors) {
          if (selector.startsWith("html[data-theme=")) continue
          if (skipped.has(selector) || floored.has(selector)) continue
          missing.push(`${file}: ${selector} (${px}px)`)
        }
      }
    }
    expect(missing).toEqual([])
  })
})
