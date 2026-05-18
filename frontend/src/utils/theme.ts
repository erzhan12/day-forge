// Pure utilities for the theme application algorithm.
//
// The split between `isKnownTheme`, `normalizeTheme`, and `applyTheme` is
// deliberate (see feature 0010 plan):
//   - `isKnownTheme` distinguishes "valid id, apply it" from "absent /
//     unknown, preserve current DOM" — used by `useThemeFromProps` to
//     avoid the partial-reload theme-reset bug.
//   - `normalizeTheme` maps any input to a valid ThemeId — used at app
//     boot and as a defensive transform on server-returned ids.
//   - `applyTheme` is the single DOM-writing primitive — never normalizes
//     internally so callers cannot accidentally write 'classic' over a
//     correct SSR value.

import type { ThemeId } from "../types"

const KNOWN_THEMES = new Set<ThemeId>([
  "classic",
  "strategic",
  "light_premium",
])

export function isKnownTheme(raw: unknown): raw is ThemeId {
  return typeof raw === "string" && KNOWN_THEMES.has(raw as ThemeId)
}

export function normalizeTheme(raw: unknown): ThemeId {
  return isKnownTheme(raw) ? raw : "classic"
}

export function applyTheme(id: ThemeId): void {
  if (typeof document === "undefined") return
  document.documentElement.dataset.theme = id
}
