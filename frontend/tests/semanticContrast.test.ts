import { describe, it, expect } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

// WCAG 2.1 contrast computation against the resolved hex/rgba values
// in app.css. The previous `accentContrast.test.ts` catches static
// pattern mismatches (fixed-bg × themed-fg); this test computes the
// *numeric* contrast of each semantic foreground/surface pair per theme,
// catching low-contrast pairings where both endpoints are valid tokens
// but their derivation produces a sub-AA result.
//
// Triggered by feature 0010 Phase 6: an earlier `.status-active` rule
// paired `var(--accent)` text with an 18% accent tint surface that
// collapsed to ~2.8:1 on Classic — caught by the reviewer's manual
// audit, not by any test. This pins the audit at CI.

const APP_CSS = readFileSync(
  resolve(__dirname, "..", "src", "app.css"),
  "utf-8",
)

// ----- WCAG math -------------------------------------------------------

function srgbToLin(c: number): number {
  const v = c / 255
  return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
}

function relativeLuminance(r: number, g: number, b: number): number {
  return 0.2126 * srgbToLin(r) + 0.7152 * srgbToLin(g) + 0.0722 * srgbToLin(b)
}

function contrastRatio(
  fg: [number, number, number],
  bg: [number, number, number],
): number {
  const L1 = relativeLuminance(...fg)
  const L2 = relativeLuminance(...bg)
  const [Llight, Ldark] = L1 > L2 ? [L1, L2] : [L2, L1]
  return (Llight + 0.05) / (Ldark + 0.05)
}

function parseColor(value: string): {
  rgb: [number, number, number]
  alpha: number
} {
  const trimmed = value.trim()
  // Hex form
  const hex = trimmed.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (hex) {
    let h = hex[1]
    if (h.length === 3) h = h.split("").map((c) => c + c).join("")
    return {
      rgb: [
        parseInt(h.slice(0, 2), 16),
        parseInt(h.slice(2, 4), 16),
        parseInt(h.slice(4, 6), 16),
      ],
      alpha: 1,
    }
  }
  // rgba / rgb form
  const rgba = trimmed.match(
    /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/,
  )
  if (rgba) {
    return {
      rgb: [Number(rgba[1]), Number(rgba[2]), Number(rgba[3])],
      alpha: rgba[4] === undefined ? 1 : Number(rgba[4]),
    }
  }
  throw new Error(`Unsupported color form: ${value}`)
}

function compositeOver(
  top: { rgb: [number, number, number]; alpha: number },
  bot: [number, number, number],
): [number, number, number] {
  const a = top.alpha
  return [
    Math.round(top.rgb[0] * a + bot[0] * (1 - a)),
    Math.round(top.rgb[1] * a + bot[1] * (1 - a)),
    Math.round(top.rgb[2] * a + bot[2] * (1 - a)),
  ]
}

// ----- Theme block parsing --------------------------------------------

function extractThemeBlock(theme: string): string {
  const re = new RegExp(`html\\[data-theme="${theme}"\\]\\s*\\{([^}]*)\\}`, "m")
  const m = APP_CSS.match(re)
  if (!m) throw new Error(`Could not find theme block for ${theme}`)
  return m[1]
}

function readToken(block: string, name: string): string {
  const re = new RegExp(`--${name}\\s*:\\s*([^;]+);`)
  const m = block.match(re)
  if (!m) throw new Error(`Token --${name} not found`)
  return m[1].trim()
}

// ----- Theme reference surfaces ---------------------------------------
//
// Translucent surfaces (Strategic) need a concrete background to
// composite against. The plan defines `--bg-panel` as the canonical
// background for cards and badges, so use it — and itself composite
// over `--bg-page` if it is also translucent (Strategic's panel is).

function resolveOpaque(
  block: string,
  tokenName: string,
  pageRgb: [number, number, number],
): [number, number, number] {
  const value = readToken(block, tokenName)
  const parsed = parseColor(value)
  return parsed.alpha === 1
    ? parsed.rgb
    : compositeOver(parsed, pageRgb)
}

function resolveSurface(
  block: string,
  tokenName: string,
  panelRgb: [number, number, number],
  pageRgb: [number, number, number],
): [number, number, number] {
  // First composite the surface over the panel; if the surface itself
  // is opaque the panel doesn't enter. Panel was already resolved
  // against the page upstream.
  const value = readToken(block, tokenName)
  const parsed = parseColor(value)
  return parsed.alpha === 1
    ? parsed.rgb
    : compositeOver(parsed, panelRgb)
}

// ----- The actual test ------------------------------------------------

const THEMES = ["classic", "strategic", "light_premium", "dark_4a"] as const
const PAIRS = ["success", "danger", "warning", "info"] as const

// WCAG AA target for normal text (small text is what badges/inline use).
// Large text (≥18pt or ≥14pt bold) needs only 3:1, but badges in this
// app render at 11–13px so we apply the stricter rule everywhere.
const TARGET = 4.5

describe("semantic foreground × surface contrast (WCAG AA)", () => {
  for (const theme of THEMES) {
    const block = extractThemeBlock(theme)
    // The page bg is always opaque in every theme — read its hex directly.
    const pageRgb = parseColor(readToken(block, "bg-page")).rgb
    // The panel may be translucent (Strategic) — composite once.
    const panelRgb = resolveOpaque(block, "bg-panel", pageRgb)

    describe(theme, () => {
      for (const pair of PAIRS) {
        it(`--${pair}-text on --${pair}-surface meets ${TARGET}:1`, () => {
          const fgRgb = resolveOpaque(block, `${pair}-text`, pageRgb)
          const surfaceRgb = resolveSurface(
            block,
            `${pair}-surface`,
            panelRgb,
            pageRgb,
          )
          const ratio = contrastRatio(fgRgb, surfaceRgb)
          expect(
            ratio,
            `Contrast ratio ${ratio.toFixed(2)}:1 (${TARGET}:1 needed). ` +
              `fg=rgb(${fgRgb.join(",")}) on bg=rgb(${surfaceRgb.join(",")})`,
          ).toBeGreaterThanOrEqual(TARGET)
        })
      }
    })
  }
})

// ----- Dark 4a control tokens (feature 0106) ---------------------------
//
// SPEC.md asks for #9CA3AF secondary text and a #6A6E75 control border on
// every Dark 4a surface. `--accent` is written as oklch() (app.css, Dark 4a
// block), which parseColor cannot read, so it is compared as its pinned sRGB
// value; the active shade is the skin's oklch(0.67 0.17 30).

const DARK_4A_ACCENT_SRGB = "#fd7562"
const DARK_4A_ACCENT_HOVER_SRGB = "#ff8571" // --accent-hover, oklch(0.77 0.17 30)
const DARK_4A_ACCENT_ACTIVE_SRGB = "#eb6553" // skin :active, oklch(0.67 0.17 30)

describe("Dark 4a control contrast (0106)", () => {
  const block = extractThemeBlock("dark_4a")
  const rgb = (token: string) => parseColor(readToken(block, token)).rgb
  const surfaces = ["bg-page", "bg-panel", "bg-input"] as const

  for (const text of ["text-secondary", "text-muted", "text-faint"]) {
    for (const surface of surfaces) {
      it(`--${text} on --${surface} meets 4.5:1`, () => {
        expect(contrastRatio(rgb(text), rgb(surface))).toBeGreaterThanOrEqual(4.5)
      })
    }
  }

  for (const surface of surfaces) {
    it(`--border-control on --${surface} meets 3:1`, () => {
      expect(contrastRatio(rgb("border-control"), rgb(surface))).toBeGreaterThanOrEqual(3)
    })
  }

  it("--control-on-bg on --bg-panel meets 3:1", () => {
    expect(contrastRatio(rgb("control-on-bg"), rgb("bg-panel"))).toBeGreaterThanOrEqual(3)
  })

  it("--accent-contrast meets 4.5:1 on --control-on-bg and on every accent fill", () => {
    const fg = rgb("accent-contrast")
    expect(contrastRatio(fg, rgb("control-on-bg"))).toBeGreaterThanOrEqual(4.5)
    for (const accent of [DARK_4A_ACCENT_SRGB, DARK_4A_ACCENT_HOVER_SRGB, DARK_4A_ACCENT_ACTIVE_SRGB]) {
      expect(contrastRatio(fg, parseColor(accent).rgb), accent).toBeGreaterThanOrEqual(4.5)
    }
  })

  it("secondary and field button states keep readable text", () => {
    // resting: --text-secondary on panel / --text-primary on field;
    // hover: --text-primary; :active: --text-primary on --bg-elevated.
    expect(contrastRatio(rgb("text-secondary"), rgb("bg-panel"))).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(rgb("text-primary"), rgb("bg-input"))).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(rgb("text-primary"), rgb("bg-elevated"))).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(rgb("danger-text"), rgb("bg-input"))).toBeGreaterThanOrEqual(4.5)
  })
})
