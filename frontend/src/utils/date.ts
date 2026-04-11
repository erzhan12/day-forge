/**
 * Format a Date as "YYYY-MM-DD" using local timezone (not UTC).
 */
export function toLocalDateString(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, "0")
  const d = String(date.getDate()).padStart(2, "0")
  return `${y}-${m}-${d}`
}

/**
 * Get today's date as "YYYY-MM-DD" in local timezone.
 */
export function todayString(): string {
  return toLocalDateString(new Date())
}

/**
 * Parse a "YYYY-MM-DD" string into a local Date (noon to avoid DST edge cases).
 */
export function parseLocalDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split("-").map(Number)
  return new Date(y, m - 1, d, 12, 0, 0)
}
