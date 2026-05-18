// Frontend theme registry.
//
// Source of truth for human-readable labels, descriptions, and selector
// preview tokens. The backend owns the persisted ids (`Theme.choices` on
// `UserPreferences`); the frontend owns the display metadata so two
// sources of truth never disagree on a color label.
//
// Preview tokens are required — the Settings selector renders a mini
// preview of each theme so users can compare before committing. A label-
// only selector would force commit-then-revert.

import type { ThemeId } from "../types"

export interface ThemePreview {
  bgPage: string
  bgPanel: string
  accent: string
  textPrimary: string
  // Sample heading rendered in the theme's display font.
  sampleHeading: string
  // CSS font family for the sample heading.
  sampleHeadingFont: string
}

export interface ThemeDefinition {
  id: ThemeId
  label: string
  description: string
  preview: ThemePreview
}

export const THEMES: ThemeDefinition[] = [
  {
    id: "classic",
    label: "Classic",
    description: "Neutral light interface. Familiar Day Forge defaults.",
    preview: {
      bgPage: "#f5f5f5",
      bgPanel: "#ffffff",
      accent: "#3b82f6",
      textPrimary: "#111827",
      sampleHeading: "Today's plan",
      sampleHeadingFont:
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    },
  },
  {
    id: "strategic",
    label: "Strategic",
    description:
      "Dark editorial atmosphere with cold blue accents and serif headings.",
    preview: {
      bgPage: "#0b1220",
      bgPanel: "#111a2e",
      accent: "#5aa6ff",
      textPrimary: "#e6ecf5",
      sampleHeading: "Today's plan",
      sampleHeadingFont: 'Georgia, "Times New Roman", serif',
    },
  },
  {
    id: "light_premium",
    label: "Light Premium",
    description:
      "Warm porcelain background with refined borders and editorial serif accents.",
    preview: {
      bgPage: "#f6f1ea",
      bgPanel: "#fffdf8",
      accent: "#2a6f97",
      textPrimary: "#1f2024",
      sampleHeading: "Today's plan",
      sampleHeadingFont: 'Georgia, "Times New Roman", serif',
    },
  },
]

export function getTheme(id: ThemeId): ThemeDefinition {
  const found = THEMES.find((t) => t.id === id)
  if (!found) {
    // Should never happen — `id` is the typed ThemeId union. Return the
    // first entry (Classic) as a runtime safety net rather than throwing.
    return THEMES[0]
  }
  return found
}
