// Reactive accessor for the user's active theme id.
//
// Why this exists: `getCategoryColor()` and other theme-aware helpers
// read `<html data-theme>` at *call time*, which is not a Vue-tracked
// dependency. Components that bind those helpers' return values
// directly in templates won't re-render when the theme changes —
// `useActiveTheme()` is the missing reactive dependency.
//
// Read order (matches DesignSelector.currentThemeId + CategoryBreakdown):
//   1. Prop, when present and a known theme id.
//   2. `document.documentElement.dataset.theme`, as preserved by
//      `useThemeFromProps` across partial reloads.
//   3. `'classic'` as the safe default.
//
// Pass the resolved id explicitly into `getCategoryColor(category,
// theme)` so the binding's reactivity flows through the computed
// rather than the imperative DOM read.

import { computed, type ComputedRef } from "vue"
import { usePage } from "@inertiajs/vue3"

import { isKnownTheme, normalizeTheme } from "../utils/theme"
import type { ThemeId } from "../types"

export function useActiveTheme(): ComputedRef<ThemeId> {
  const page = usePage()
  return computed(() => {
    const propTheme = page.props.ui_preferences?.theme
    if (isKnownTheme(propTheme)) return propTheme
    const domTheme =
      typeof document !== "undefined"
        ? document.documentElement.dataset.theme
        : undefined
    return normalizeTheme(domTheme)
  })
}
