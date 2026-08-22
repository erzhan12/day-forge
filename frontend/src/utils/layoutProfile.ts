import type { ThemeId } from "../types"

export type LayoutProfile = "classic" | "4a"

export function layoutForTheme(themeId: ThemeId): LayoutProfile {
  return themeId === "dark_4a" ? "4a" : "classic"
}

export function pxPerMinuteForLayout(layout: LayoutProfile): number {
  return layout === "4a" ? 1.6 : 2
}
