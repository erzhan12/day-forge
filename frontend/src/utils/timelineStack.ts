// Stack layout for the Dark 4a timeline (feature 0106).
//
// The linear layout places every item at `(start − origin) × pxPerMinute`, so a
// 5-minute block is 10 px tall and a free afternoon takes hundreds of pixels.
// The stack walks the display items in order instead: blocks get a 28 px
// floor, gaps touching a window edge and spacers are capped at the edge-stub
// height, and each item starts where the previous one ended. A gap between two
// blocks stays on the true scale (feature 0110) so the amount of free time
// stays visible. A piecewise-linear axis map built from
// the same segments converts minutes to pixels and back for hour labels, the
// now line and drag.
//
// Input is the unchanged output of `buildBaseDisplayItems`; calendar events
// never reach this module.
import {
  STUB_MINUTES,
  minutesToTime,
  timeToMinutes,
  type ScheduleDisplayItem,
  type ScheduleWindowBounds,
} from "./scheduleTime"

export const MIN_BLOCK_PX = 28
export const COMPACT_BELOW_PX = 36

export type StackSegmentKind = "block" | "gap" | "spacer"

export interface StackSegment {
  kind: StackSegmentKind
  startMin: number
  endMin: number
  topPx: number
  heightPx: number
  /** Rendered shorter than its true scale (an edge stub or a spacer). */
  compressed: boolean
  /** Rendered taller than its true scale (a block raised to the floor). */
  stretched: boolean
}

export interface StackedItem {
  /** Gaps carry their trimmed and coalesced interval. */
  item: ScheduleDisplayItem
  topPx: number
  heightPx: number
  /** A block rendered below COMPACT_BELOW_PX. */
  compact: boolean
  compressed: boolean
  /** Gap rows touching exactly one window edge while compressed. */
  edgeHint: "earlier" | "later" | null
}

export interface AxisMap {
  segments: StackSegment[]
  timeToPx: (minute: number) => number
  pxToTime: (px: number) => number
}

export interface TimelineStack extends AxisMap {
  /** Rendered items in stack order; spacers are geometry only. */
  items: StackedItem[]
  canvasHeightPx: number
  hourTicks: Array<{ minute: number; topPx: number }>
  /** First segment in stack order whose half-open range holds `minute`. */
  segmentAt: (minute: number) => StackSegment | null
}

interface Interval {
  item: ScheduleDisplayItem
  start: number
  end: number
}

/**
 * Trim free items to the running maximum end of earlier blocks (a legacy
 * overlap can make a later block end before an enclosing one), drop the ones
 * that become empty, and merge time-contiguous gaps — today's trailing split
 * at "now" — into one logical gap. Spacers are never merged.
 */
function normaliseItems(items: ScheduleDisplayItem[]): Interval[] {
  const out: Interval[] = []
  let coveredUntil = Number.NEGATIVE_INFINITY
  for (const item of items) {
    const start = timeToMinutes(item.start_time)
    const end = timeToMinutes(item.end_time)
    if (item.type === "block" || item.type === "block-with-now") {
      out.push({ item, start, end })
      coveredUntil = Math.max(coveredUntil, end)
      continue
    }
    const trimmedStart = Math.max(start, coveredUntil)
    if (trimmedStart >= end) continue
    const previous = out.at(-1)
    const isGap = item.type === "gap" || item.type === "gap-with-now"
    if (isGap && previous && previous.item.type === "gap" && previous.end === trimmedStart) {
      previous.end = end
      continue
    }
    out.push({ item: { ...item, type: isGap ? "gap" : item.type }, start: trimmedStart, end })
  }
  return out.map(({ item, start, end }) =>
    item.type === "block" || item.type === "block-with-now"
      ? { item, start, end }
      : {
          item: {
            type: item.type,
            start_time: minutesToTime(start),
            end_time: minutesToTime(end),
            duration_minutes: end - start,
          },
          start,
          end,
        },
  )
}

function edgeHintFor(
  start: number,
  end: number,
  compressed: boolean,
  window: Pick<ScheduleWindowBounds, "startMinutes" | "endMinutes">,
): "earlier" | "later" | null {
  if (!compressed) return null
  const atStart = start === window.startMinutes
  const atEnd = end === window.endMinutes
  if (atStart && !atEnd) return "earlier"
  if (atEnd && !atStart) return "later"
  return null
}

export function buildTimelineStack(
  items: ScheduleDisplayItem[],
  pxPerMinute: number,
  window: Pick<ScheduleWindowBounds, "startMinutes" | "endMinutes">,
): TimelineStack {
  const gapCapPx = STUB_MINUTES * pxPerMinute
  const segments: StackSegment[] = []
  const stacked: StackedItem[] = []
  let y = 0

  for (const { item, start, end } of normaliseItems(items)) {
    const raw = (end - start) * pxPerMinute
    const isBlock = item.type === "block" || item.type === "block-with-now"
    const kind: StackSegmentKind = isBlock ? "block" : item.type === "spacer" ? "spacer" : "gap"
    // Only edge gaps and spacers are capped; a mid-day gap keeps its scale.
    const capped = kind === "spacer" || start === window.startMinutes || end === window.endMinutes
    const heightPx = isBlock ? Math.max(raw, MIN_BLOCK_PX) : capped ? Math.min(raw, gapCapPx) : raw
    const compressed = heightPx < raw
    const stretched = heightPx > raw
    segments.push({ kind, startMin: start, endMin: end, topPx: y, heightPx, compressed, stretched })
    if (kind !== "spacer") {
      stacked.push({
        item,
        topPx: y,
        heightPx,
        compact: isBlock && heightPx < COMPACT_BELOW_PX,
        compressed,
        edgeHint: kind === "gap" ? edgeHintFor(start, end, compressed, window) : null,
      })
    }
    y += heightPx
  }

  const canvasHeightPx = y

  const segmentAt = (minute: number): StackSegment | null =>
    segments.find((s) => s.startMin <= minute && minute < s.endMin) ?? null

  const timeToPx = (minute: number): number => {
    const segment = segmentAt(minute)
    if (segment) {
      return segment.topPx + ((minute - segment.startMin) / (segment.endMin - segment.startMin)) * segment.heightPx
    }
    if (segments.length === 0 || minute < segments[0].startMin) return 0
    // A minute in no segment (past the end, or between a trimmed overlap and
    // the next item) maps to the top of the next segment that starts later.
    const next = segments.find((s) => s.startMin > minute)
    return next ? next.topPx : canvasHeightPx
  }

  const pxToTime = (px: number): number => {
    if (segments.length === 0) return window.startMinutes
    if (px <= 0) return segments[0].startMin
    const segment = segments.find((s) => s.topPx <= px && px < s.topPx + s.heightPx)
    if (!segment) return segments[segments.length - 1].endMin
    return segment.startMin + ((px - segment.topPx) / segment.heightPx) * (segment.endMin - segment.startMin)
  }

  const hourTicks: Array<{ minute: number; topPx: number }> = []
  if (segments.length > 0) {
    const first = segments[0].startMin
    const last = Math.max(...segments.map((s) => s.endMin))
    for (let minute = Math.ceil(first / 60) * 60; minute < last; minute += 60) {
      const segment = segmentAt(minute)
      if (!segment) continue
      const onStart = segment.startMin === minute
      const inside = segment.kind === "block" || (segment.kind === "gap" && !segment.compressed)
      if (onStart || inside) hourTicks.push({ minute, topPx: timeToPx(minute) })
    }
  }

  return { items: stacked, segments, canvasHeightPx, hourTicks, segmentAt, timeToPx, pxToTime }
}
