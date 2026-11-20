// Stable stripe colour for an external calendar (feature 0105). Events carry
// no provider colour, so the client hashes the calendar name into a small
// themed palette (`--calendar-hue-N` in app.css). Display-only.

export const CALENDAR_HUE_COUNT = 6

// FNV-1a, 32-bit. `>>> 0` keeps the result unsigned so the modulo is never
// negative.
function fnv1a(text: string): number {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return hash >>> 0
}

export function calendarHueIndex(name: string): number {
  if (!name) return 0
  return fnv1a(name) % CALENDAR_HUE_COUNT
}

export function calendarColorVar(name: string): string {
  return `var(--calendar-hue-${calendarHueIndex(name) + 1})`
}
