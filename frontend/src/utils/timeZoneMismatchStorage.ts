export const TIME_ZONE_MISMATCH_STORAGE_KEY = "day-forge:timezone-mismatch:handled"

const memoryHandled = new Set<string>()

function storedHandled(): Set<string> {
  try {
    const raw = localStorage.getItem(TIME_ZONE_MISMATCH_STORAGE_KEY)
    if (raw === null) return new Set()
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed)
      ? new Set(parsed.filter((value): value is string => typeof value === "string"))
      : new Set()
  } catch {
    return new Set()
  }
}

export function isTimeZoneHandled(timeZone: string): boolean {
  return memoryHandled.has(timeZone) || storedHandled().has(timeZone)
}

export function markTimeZoneHandled(timeZone: string): void {
  memoryHandled.add(timeZone)
  try {
    const values = storedHandled()
    values.add(timeZone)
    localStorage.setItem(TIME_ZONE_MISMATCH_STORAGE_KEY, JSON.stringify([...values]))
  } catch {
    // The in-memory set preserves the dismissal for this tab.
  }
}
