import type { ThemeId } from "../types"

export type LayoutProfile = "classic" | "4a"

export function layoutForTheme(themeId: ThemeId): LayoutProfile {
  return themeId === "dark_4a" ? "4a" : "classic"
}

export function pxPerMinuteForLayout(layout: LayoutProfile): number {
  switch (layout) {
    case "4a":
    case "classic":
      return 2
    default: {
      const _exhaustive: never = layout
      return _exhaustive
    }
  }
}
