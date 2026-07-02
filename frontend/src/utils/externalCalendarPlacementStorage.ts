export type ExternalCalendarPlacement = "sidebar" | "center"

export const EXTERNAL_CALENDAR_PLACEMENT_KEY =
  "day-forge:external-calendar:placement"

// Default: left sidebar (post-PR #90). Only the literal string "center"
// selects the legacy center-column placement; missing/malformed values fall
// back to "sidebar".
export function readExternalCalendarPlacement(): ExternalCalendarPlacement {
  try {
    const raw = localStorage.getItem(EXTERNAL_CALENDAR_PLACEMENT_KEY)
    if (raw === null) return "sidebar"
    return JSON.parse(raw) === "center" ? "center" : "sidebar"
  } catch {
    return "sidebar"
  }
}

export function writeExternalCalendarPlacement(
  v: ExternalCalendarPlacement,
): void {
  try {
    localStorage.setItem(EXTERNAL_CALENDAR_PLACEMENT_KEY, JSON.stringify(v))
  } catch {
    // private-mode browsers / disk-quota — fall back to in-memory only
  }
}
