// Wires every authenticated page's `ui_preferences` prop into the DOM
// `<html data-theme="…">` attribute. Each authenticated page calls
// `useThemeFromProps()` once in `setup()`.
//
// Behavior contract (see feature 0010 plan):
//   - When `ui_preferences.theme` is present and a recognized id: apply.
//   - When absent or unrecognized: PRESERVE the current `data-theme`.
//     This protects partial Inertia reloads that omit the prop from
//     resetting a Strategic user back to Classic.

import { watch } from "vue"
import { usePage } from "@inertiajs/vue3"

import { applyTheme, isKnownTheme, normalizeTheme } from "../utils/theme"

export function useThemeFromProps() {
  const page = usePage()
  watch(
    () => page.props.ui_preferences?.theme,
    (raw) => {
      if (raw === undefined || raw === null) return // preserve SSR DOM
      if (!isKnownTheme(raw)) return // preserve SSR DOM
      // `normalizeTheme(raw)` is defensively symmetric here. After
      // `isKnownTheme(raw)` narrows to ThemeId, normalizeTheme returns it
      // unchanged. The wrapper stays so the call signature matches the
      // other two sanctioned application sites (app boot + reload-error
      // fallback) where the input is genuinely untrusted.
      applyTheme(normalizeTheme(raw))
    },
    { immediate: true },
  )
}
