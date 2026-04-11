// Shared constants and time helpers for schedule layout

export const DAY_START = "06:00"
export const DAY_END = "23:00"
export const DAY_START_MINUTES = 360 // 06:00
export const DAY_END_MINUTES = 1380 // 23:00
export const PX_PER_MINUTE = 2 // 120px per hour, 30px per 15min
export const SNAP_MINUTES = 5

export function timeToMinutes(time: string): number {
  const [h, m] = time.split(":").map(Number)
  return h * 60 + m
}

export function minutesToTime(mins: number): string {
  const h = String(Math.floor(mins / 60)).padStart(2, "0")
  const m = String(mins % 60).padStart(2, "0")
  return `${h}:${m}`
}

export function snapToGrid(minutes: number): number {
  return Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES
}

export function clampToDay(minutes: number): number {
  return Math.max(DAY_START_MINUTES, Math.min(DAY_END_MINUTES, minutes))
}
