import { describe, it, expect } from "vitest"
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join, resolve } from "node:path"

// Static scan: a Vue component must NEVER pair `background: var(--accent)`
// (or `var(--accent-hover)`) with a hardcoded white foreground. The
// `--accent-contrast` token exists exactly to handle this — Strategic's
// accent is `#5aa6ff` and white-on-that is ~2.3:1, below WCAG AA's
// 4.5:1 for normal text AND below the 3:1 non-text minimum.
//
// This test caught feature 0010's bulk-migration miss where four buttons
// got `background: var(--accent)` but kept `color: white`. It guards
// against the same regression slipping back in.

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const s = statSync(p)
    if (s.isDirectory()) {
      out.push(...walk(p))
    } else if (p.endsWith(".vue")) {
      out.push(p)
    }
  }
  return out
}

const SRC = resolve(__dirname, "..", "src")
const VUE_FILES = walk(SRC)

// Matches a single CSS rule block. Captures the body for inspection.
// Vue SFCs have one `<style scoped>` per file in this project, so the
// regex runs against the entire file but only matches inside `{ … }`
// blocks (which excludes the template).
const RULE_BLOCK = /\{([^{}]*)\}/g

const WHITE_RE = /\bcolor\s*:\s*(white|#fff|#ffffff)\b/i
const ACCENT_BG_RE = /\bbackground(?:-color)?\s*:\s*var\(--accent(?:-hover)?\)/

// A hardcoded-hex background pattern. Excludes `var(...)` and named
// keywords like `transparent`/`currentColor` — only literal hex matters.
const HEX_BG_RE =
  /\bbackground(?:-color)?\s*:\s*#[0-9a-fA-F]{3,8}\b/
// Inline `rgba(...)` / `rgb(...)` background that doesn't depend on a
// CSS variable. These are theme-invariant by construction.
const RGB_BG_RE =
  /\bbackground(?:-color)?\s*:\s*rgba?\(\s*\d+\s*,/
// Theme-dependent foreground tokens. If the foreground shifts between
// light and dark themes, the background must shift with it.
const THEMED_FG_RE =
  /\bcolor\s*:\s*var\(--(text-(primary|secondary|muted|faint)|success-text|danger-text|warning-text|accent)\)/

// A small allowlist for rules that legitimately pair a fixed-color
// background with a theme-token foreground. Each entry is a regex
// matched against the snippet (path + body), so it can target a
// specific selector. Keep this list narrow and document each entry's
// reason — anything not allowlisted must theme its background.
const FIXED_BG_THEMED_FG_ALLOWLIST: { reason: string; pattern: RegExp }[] = [
  // CommandBar is the AI command cockpit (terminal aesthetic in every
  // theme). See the leading comment in CommandBar.vue's <style scoped>.
  {
    reason: "CommandBar intentionally theme-invariant (AI cockpit)",
    pattern: /components\/CommandBar\.vue/,
  },
]

function isAllowlisted(pathSnippet: string): { ok: boolean; reason?: string } {
  for (const entry of FIXED_BG_THEMED_FG_ALLOWLIST) {
    if (entry.pattern.test(pathSnippet)) return { ok: true, reason: entry.reason }
  }
  return { ok: false }
}

describe("--accent-contrast contract (no white-on-accent in any Vue file)", () => {
  it("every component pairs accent backgrounds with var(--accent-contrast), never white", () => {
    const offenders: string[] = []
    for (const path of VUE_FILES) {
      const text = readFileSync(path, "utf-8")
      // Iterate rule blocks; flag any block that has BOTH an accent
      // background and a white foreground.
      for (const m of text.matchAll(RULE_BLOCK)) {
        const body = m[1]
        if (ACCENT_BG_RE.test(body) && WHITE_RE.test(body)) {
          // Trim to a short identifying snippet for the failure message.
          const snippet = body
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .slice(0, 6)
            .join(" | ")
          offenders.push(
            `${path.replace(SRC + "/", "")}\n    rule: { ${snippet} }`,
          )
        }
      }
    }
    expect(
      offenders,
      `White text on var(--accent) fails contrast in the Strategic theme ` +
        `(~2.3:1 vs WCAG AA 4.5:1). Use var(--accent-contrast) instead. ` +
        `Offenders:\n${offenders.join("\n")}`,
    ).toEqual([])
  })
})

describe("fixed-background × themed-foreground contract", () => {
  // Pattern: a CSS rule with a hardcoded hex / rgba background paired
  // with a theme-token foreground (e.g. var(--success-text)).
  //
  // Why it's a bug: theme-token foregrounds shift across themes
  // (Strategic flips light↔dark for most semantic colors), but a fixed
  // background does not. In at least one theme the pair collapses
  // light-on-light or dark-on-dark. Strategic is the usual victim:
  //   - var(--success-text) = #6ee7b7 over #d1fae5  → light-on-light
  //   - var(--text-secondary) = #c2cbdc over rgba(249,250,251,0.85) → unreadable
  //
  // This rule generalizes the previously-fixed accent-contrast scan to
  // catch the same shape across every semantic family.
  it("every component themes its background to match a themed foreground", () => {
    const offenders: string[] = []
    for (const path of VUE_FILES) {
      const text = readFileSync(path, "utf-8")
      for (const m of text.matchAll(RULE_BLOCK)) {
        const body = m[1]
        const hasFixedBg = HEX_BG_RE.test(body) || RGB_BG_RE.test(body)
        const hasThemedFg = THEMED_FG_RE.test(body)
        if (!(hasFixedBg && hasThemedFg)) continue
        const relPath = path.replace(SRC + "/", "")
        const snippet = body
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean)
          .slice(0, 8)
          .join(" | ")
        const pathSnippet = `${relPath} | ${snippet}`
        const allow = isAllowlisted(pathSnippet)
        if (allow.ok) continue
        offenders.push(`${relPath}\n    rule: { ${snippet} }`)
      }
    }
    expect(
      offenders,
      `Fixed-color background paired with a theme-token foreground. ` +
        `The foreground shifts across themes but the background does not, ` +
        `so contrast collapses in at least one theme (usually Strategic). ` +
        `Either tokenize the background (e.g. var(--success-surface), ` +
        `color-mix(in srgb, var(--accent) 18%, transparent)), or pair ` +
        `the fixed background with a fixed foreground. Offenders:\n` +
        offenders.join("\n"),
    ).toEqual([])
  })
})
