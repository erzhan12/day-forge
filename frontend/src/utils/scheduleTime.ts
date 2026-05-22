// Shared constants and time helpers for schedule layout
import type { TimeBlock } from "../types"

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

/**
 * Returns the block containing `nowMinutes` on a half-open `[start, end)`
 * interval. Returns `null` when `nowDate` is `null` (off-today) or no block
 * matches. Overlapping matches resolve by `(start_time, sort_order)`.
 */
export function findCurrentBlock(
  blocks: TimeBlock[],
  nowMinutes: number,
  nowDate: string | null,
): TimeBlock | null {
  if (nowDate === null) return null

  const matchingBlocks = blocks
    .filter((block) => {
      const start = timeToMinutes(block.start_time)
      const end = timeToMinutes(block.end_time)
      return start <= nowMinutes && nowMinutes < end
    })
    // Overlap should not happen, but choose the same ordered block the API
    // and NowLine iteration would surface first.
    .sort((a, b) => {
      const startDelta = timeToMinutes(a.start_time) - timeToMinutes(b.start_time)
      return startDelta !== 0 ? startDelta : a.sort_order - b.sort_order
    })

  return matchingBlocks[0] ?? null
}

/**
 * Minutes until `block.end_time`. Half-open window — returns `null` before
 * `start_time` and at/after `end_time`.
 */
export function remainingMinutesForBlock(
  block: TimeBlock,
  nowMinutes: number,
): number | null {
  const start = timeToMinutes(block.start_time)
  const end = timeToMinutes(block.end_time)
  if (nowMinutes < start || nowMinutes >= end) return null

  return end - nowMinutes
}

/**
 * "Xm" / "Xh" / "Xh Ym" duration label. Negative or zero input returns
 * `"0m"` (caller-error path; this leaf formatter never throws).
 */
export function formatDurationMinutes(minutes: number): string {
  if (minutes <= 0) return "0m"
  if (minutes < 60) return `${minutes}m`

  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return remainder === 0 ? `${hours}h` : `${hours}h ${remainder}m`
}

/** "Xm left" / "Xh left" / "Xh Ym left" — appends " left" to `formatDurationMinutes`. */
export function formatRemainingMinutes(minutes: number): string {
  return `${formatDurationMinutes(minutes)} left`
}
