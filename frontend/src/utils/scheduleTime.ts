// Shared constants and time helpers for schedule layout
import type { TimeBlock } from "../types"

export const DAY_START = "06:00"
export const DAY_END = "23:00"
export const DAY_START_MINUTES = 360 // 06:00
export const DAY_END_MINUTES = 1380 // 23:00
export const PX_PER_MINUTE = 2 // 120px per hour, 30px per 15min
export const SNAP_MINUTES = 5
export const STUB_MINUTES = 30

export interface RenderBounds {
  renderStart: number
  renderEnd: number
}

export interface ScheduleDisplayItem {
  type: "block" | "gap" | "block-with-now" | "gap-with-now"
  block?: TimeBlock
  start_time: string
  end_time: string
  duration_minutes: number
  render_minutes?: number
  compact?: boolean
}

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

/** Blocks overlapping [DAY_START, DAY_END), sorted by (start_time, sort_order). */
export function filterVisibleBlocks(blocks: TimeBlock[]): TimeBlock[] {
  return blocks
    .filter(
      (b) =>
        timeToMinutes(b.end_time) > DAY_START_MINUTES &&
        timeToMinutes(b.start_time) < DAY_END_MINUTES,
    )
    .sort((a, b) => {
      const startDelta =
        timeToMinutes(a.start_time) - timeToMinutes(b.start_time)
      return startDelta !== 0 ? startDelta : a.sort_order - b.sort_order
    })
}

/** Origin-shift linear render bounds for compact edge stubs. */
export function computeRenderBounds(blocks: TimeBlock[]): RenderBounds {
  const visible = filterVisibleBlocks(blocks)
  if (visible.length === 0) {
    return { renderStart: DAY_START_MINUTES, renderEnd: DAY_END_MINUTES }
  }

  const firstStart = Math.max(
    timeToMinutes(visible[0].start_time),
    DAY_START_MINUTES,
  )
  const lastEnd = Math.min(
    timeToMinutes(visible[visible.length - 1].end_time),
    DAY_END_MINUTES,
  )

  const leadingGap = firstStart - DAY_START_MINUTES
  const trailingGap = DAY_END_MINUTES - lastEnd

  return {
    renderStart:
      leadingGap > STUB_MINUTES ? firstStart - STUB_MINUTES : DAY_START_MINUTES,
    renderEnd:
      trailingGap > STUB_MINUTES ? lastEnd + STUB_MINUTES : DAY_END_MINUTES,
  }
}

/**
 * Build the block/gap list before now-marker splicing. Edge gaps may
 * compress to stub height; `activeRender*` is frozen during drag.
 */
export function buildBaseDisplayItems(
  blocks: TimeBlock[],
  activeRenderStart: number,
  activeRenderEnd: number,
): ScheduleDisplayItem[] {
  const items: ScheduleDisplayItem[] = []
  const visibleBlocks = filterVisibleBlocks(blocks)

  if (visibleBlocks.length === 0) {
    items.push({
      type: "gap",
      start_time: DAY_START,
      end_time: DAY_END,
      duration_minutes: DAY_END_MINUTES - DAY_START_MINUTES,
    })
    return items
  }

  const firstStart = Math.max(
    timeToMinutes(visibleBlocks[0].start_time),
    DAY_START_MINUTES,
  )
  if (firstStart > DAY_START_MINUTES) {
    const compressed = activeRenderStart > DAY_START_MINUTES
    items.push({
      type: "gap",
      start_time: DAY_START,
      end_time: minutesToTime(firstStart),
      duration_minutes: firstStart - DAY_START_MINUTES,
      ...(compressed
        ? {
            render_minutes: Math.max(0, firstStart - activeRenderStart),
            compact: true,
          }
        : {}),
    })
  }

  for (let i = 0; i < visibleBlocks.length; i++) {
    const block = visibleBlocks[i]
    const clampedStart = Math.max(
      timeToMinutes(block.start_time),
      DAY_START_MINUTES,
    )
    const clampedEnd = Math.min(
      timeToMinutes(block.end_time),
      DAY_END_MINUTES,
    )
    items.push({
      type: "block",
      block,
      start_time: minutesToTime(clampedStart),
      end_time: minutesToTime(clampedEnd),
      duration_minutes: clampedEnd - clampedStart,
    })

    if (i < visibleBlocks.length - 1) {
      const gapStart = clampedEnd
      const nextStart = Math.max(
        timeToMinutes(visibleBlocks[i + 1].start_time),
        DAY_START_MINUTES,
      )
      const gapMinutes = nextStart - gapStart
      if (gapMinutes > 0) {
        items.push({
          type: "gap",
          start_time: minutesToTime(gapStart),
          end_time: minutesToTime(nextStart),
          duration_minutes: gapMinutes,
        })
      }
    }
  }

  const lastEnd = Math.min(
    timeToMinutes(visibleBlocks[visibleBlocks.length - 1].end_time),
    DAY_END_MINUTES,
  )
  if (lastEnd < DAY_END_MINUTES) {
    const compressed = activeRenderEnd < DAY_END_MINUTES
    items.push({
      type: "gap",
      start_time: minutesToTime(lastEnd),
      end_time: DAY_END,
      duration_minutes: DAY_END_MINUTES - lastEnd,
      ...(compressed
        ? {
            render_minutes: Math.max(0, activeRenderEnd - lastEnd),
            compact: true,
          }
        : {}),
    })
  }

  return items
}

/**
 * Splice a now-marker into the base display list: the single item whose
 * half-open `[start, end)` range contains `nowMinutes` becomes its
 * `-with-now` variant, preserving every geometry field (`render_minutes`,
 * `compact`) via spread — so a compressed edge stub stays compact and keeps
 * its rendered height through the splice. Returns the list unchanged when
 * `nowDate` is `null` (off-today) or `nowMinutes` is `null`.
 */
export function spliceNowMarker(
  items: ScheduleDisplayItem[],
  nowMinutes: number | null,
  nowDate: string | null,
): ScheduleDisplayItem[] {
  if (nowDate === null || nowMinutes === null) return items

  const result: ScheduleDisplayItem[] = []
  let inserted = false

  for (const item of items) {
    const start = timeToMinutes(item.start_time)
    const end = timeToMinutes(item.end_time)

    if (inserted || nowMinutes < start || nowMinutes >= end) {
      result.push(item)
      continue
    }

    inserted = true
    result.push({
      ...item,
      type: item.type === "gap" ? "gap-with-now" : "block-with-now",
    })
  }

  return result
}

/**
 * CSS `top` percentage for a now-marker inside an item, proportional to the
 * item's SEMANTIC `[start, end)` range — not its rendered height. CSS maps the
 * percentage onto the rendered height, so a compressed edge stub still
 * positions the marker proportionally (approximate, per spec). Returns `"0%"`
 * when `nowMinutes` is `null` (off-today) or the span is non-positive.
 */
export function nowOffsetPercent(
  startTime: string,
  endTime: string,
  nowMinutes: number | null,
): string {
  if (nowMinutes === null) return "0%"
  const start = timeToMinutes(startTime)
  const end = timeToMinutes(endTime)
  const span = end - start
  if (span <= 0) return "0%"
  return ((nowMinutes - start) / span) * 100 + "%"
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
