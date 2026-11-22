import { describe, expect, it } from "vitest"
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, resolve } from "node:path"
import pinned from "./fixtures/themeTokenBlocks.json"

// Feature 0106 works only inside Dark 4a. These guards keep every other theme
// byte-for-byte on its token values and keep the shared control skin inert
// outside `html[data-theme="dark_4a"]`.

const SRC = resolve(__dirname, "..", "src")
const APP_CSS = readFileSync(resolve(SRC, "app.css"), "utf-8")

const SELECTORS: Record<string, string> = {
  root: ":root",
  classic: 'html[data-theme="classic"]',
  strategic: 'html[data-theme="strategic"]',
  light_premium: 'html[data-theme="light_premium"]',
  dark_4a: 'html[data-theme="dark_4a"]',
}

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "")
}

function tokenBlock(key: string): Record<string, string> {
  const selector = SELECTORS[key]
  const start = APP_CSS.indexOf(`${selector} {`)
  if (start < 0) throw new Error(`Missing token block ${selector}`)
  const end = APP_CSS.indexOf("}", start)
  const body = stripComments(APP_CSS.slice(start + selector.length + 2, end))
  const map: Record<string, string> = {}
  for (const declaration of body.split(";")) {
    const text = declaration.trim()
    if (!text) continue
    const colon = text.indexOf(":")
    map[text.slice(0, colon).trim()] = text.slice(colon + 1).replace(/\s+/g, " ").trim()
  }
  return map
}

const SKIN_START = "/* == Dark 4a control skin (feature 0106) == */"
const SKIN_END = "/* == end Dark 4a control skin == */"

function skinSection(): string {
  const start = APP_CSS.indexOf(SKIN_START)
  const end = APP_CSS.indexOf(SKIN_END)
  if (start < 0 || end < start) throw new Error("Dark 4a control skin section not found")
  return stripComments(APP_CSS.slice(start + SKIN_START.length, end))
}

// Selector lists of every style rule in a CSS fragment, descending into
// at-rule blocks (@media, @supports) without treating their preludes as
// selectors.
function ruleSelectors(css: string): string[] {
  const out: string[] = []
  let depth = 0
  let prelude = ""
  for (const ch of css) {
    if (ch === "{") {
      const head = prelude.trim()
      if (head && !head.startsWith("@")) out.push(head)
      depth += 1
      prelude = ""
    } else if (ch === "}") {
      depth -= 1
      prelude = ""
    } else if (ch === ";") {
      prelude = ""
    } else {
      prelude += ch
    }
  }
  expect(depth).toBe(0)
  return out
}

function vueFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) out.push(...vueFiles(path))
    else if (path.endsWith(".vue")) out.push(path)
  }
  return out
}

describe("Dark 4a scope (0106)", () => {
  it("leaves the :root, classic, strategic and light_premium token blocks unchanged", () => {
    for (const key of ["root", "classic", "strategic", "light_premium"] as const) {
      expect(tokenBlock(key), key).toEqual(pinned[key])
    }
  })

  it("defines --border-control and --control-on-bg only in the dark_4a block", () => {
    const dark = tokenBlock("dark_4a")
    expect(dark["--border-control"]).toBeDefined()
    expect(dark["--control-on-bg"]).toBeDefined()
    const definitions = stripComments(APP_CSS).match(/--(border-control|control-on-bg)\s*:/g) ?? []
    expect(definitions).toHaveLength(2)
  })

  it('prefixes every selector of the control skin section with html[data-theme="dark_4a"]', () => {
    const selectors = ruleSelectors(skinSection())
    expect(selectors.length).toBeGreaterThan(0)
    for (const list of selectors) {
      for (const selector of list.split(",")) {
        expect(selector.trim(), list).toMatch(/^html\[data-theme="dark_4a"\]\s/)
      }
    }
  })

  it("no Vue file uses :global(html…) followed by a descendant selector", () => {
    const offenders: string[] = []
    for (const file of vueFiles(SRC)) {
      const source = readFileSync(file, "utf-8")
      for (const match of source.matchAll(/:global\(\s*html[^)]*\)\s*[^\s{,]/g)) {
        offenders.push(`${file}: ${match[0]}`)
      }
    }
    expect(offenders).toEqual([])
  })
})
