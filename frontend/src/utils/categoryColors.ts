// Single source of truth for category → swatch colour. Imported by
// TimeBlock.vue (the canonical block renderer) and by the analytics
// components (CategoryBreakdown). Keeping this in one module avoids the
// drift bug where the schedule view and the analytics view show
// different colours for the same category.
//
// Values are intentionally hex (not CSS vars). `CategoryBreakdown.vue`
// produces a 20%-alpha tint via `${color}33` — concatenation that
// silently produces invalid CSS if the value is `var(--cat-focus)`.
// Per-theme overrides (see below) must remain hex strings.

import type { TimeBlock } from "../types"
import type { ThemeId } from "../types"
import { isKnownTheme } from "./theme"

type Category = TimeBlock["category"]

// Base palette — used by Classic and as the fallback for any theme that
// does not override a particular category.
export const categoryColors: Record<Category, string> = {
  work: "#3B82F6",
  personal: "#8B5CF6",
  health: "#10B981",
  other: "#6B7280",
}

// Per-theme overrides for the WCAG 1.4.11 (3:1) contrast audit
// (feature 0010 Phase 4 exit gate). Each entry below replaces the base
// hex when the base value fails 3:1 against the panel background for
// that theme. Values MUST be hex strings — the alpha-suffix
// `${color}33` concatenation in CategoryBreakdown.vue depends on it.
//
// Audit results (contrast vs effective panel background, target 3:1):
//   work     classic         3.68  OK
//   personal classic         4.23  OK
//   health   classic         2.54  FAIL  → override #059669 (3.77)
//   other    classic         4.83  OK
//   work     strategic       4.72  OK
//   personal strategic       4.10  OK
//   health   strategic       6.84  OK
//   other    strategic       3.59  OK
//   work     light_premium   3.62  OK
//   personal light_premium   4.17  OK
//   health   light_premium   2.50  FAIL  → override #059669 (3.71)
//   other    light_premium   4.76  OK
//
// Strategic's effective panel is the rgba(20,28,48,0.78) panel blended
// over the #0b1220 page (~#121a2c) — the audit measures the composite.
const categoryOverrides: Partial<
  Record<ThemeId, Partial<Record<Category, string>>>
> = {
  classic: { health: "#059669" },
  light_premium: { health: "#059669" },
}

function activeThemeId(): ThemeId {
  if (typeof document === "undefined") return "classic"
  const raw = document.documentElement.dataset.theme
  return isKnownTheme(raw) ? raw : "classic"
}

/**
 * Return the (possibly theme-overridden) hex color for ``category``.
 *
 * Resolves the active theme from the live ``<html data-theme>``
 * attribute, so the function reflects the current selection without
 * needing to thread the theme through every call site.
 */
export function getCategoryColor(category: Category, theme?: ThemeId): string {
  const id = theme ?? activeThemeId()
  return categoryOverrides[id]?.[category] ?? categoryColors[category]
}
