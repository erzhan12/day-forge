// Per-section collapsed state of the Dark 4a sources rail (feature 0105).
// Every section defaults to expanded; the default lives here so callers
// always receive a complete object.

export const EXTERNAL_RAIL_COLLAPSED_KEY = "day-forge:external-rail:collapsed"

export type ExternalRailSection = "todoist" | "habitica" | "calendars"

export type ExternalRailCollapsed = Record<ExternalRailSection, boolean>

const SECTIONS: readonly ExternalRailSection[] = ["todoist", "habitica", "calendars"]

function expandedState(): ExternalRailCollapsed {
  return { todoist: false, habitica: false, calendars: false }
}

export function readExternalRailCollapsed(): ExternalRailCollapsed {
  const result = expandedState()
  try {
    const raw = localStorage.getItem(EXTERNAL_RAIL_COLLAPSED_KEY)
    if (raw === null) return result
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return result
    for (const section of SECTIONS) {
      // Only a literal `true` collapses; anything else stays expanded.
      if ((parsed as Record<string, unknown>)[section] === true) result[section] = true
    }
    return result
  } catch {
    return result
  }
}

export function writeExternalRailCollapsed(value: ExternalRailCollapsed): void {
  try {
    localStorage.setItem(EXTERNAL_RAIL_COLLAPSED_KEY, JSON.stringify(value))
  } catch {
    // private-mode browsers / disk-quota — fall back to in-memory only
  }
}
