// Shared constants and time helpers for schedule layout
import type { TimeBlock } from "../types"

export const DAY_START = "06:00"
export const DAY_END = "23:00"
export const DAY_START_MINUTES = 360 // 06:00
export const DAY_END_MINUTES = 1380 // 23:00
export const PX_PER_MINUTE = 2 // 120px per hour, 30px per 15min
export const SNAP_MINUTES = 5
export const STUB_MINUTES = 30

export interface ScheduleWindowBounds {
  start: string
  end: string
  startMinutes: number
  endMinutes: number
}

export const DEFAULT_SCHEDULE_WINDOW: ScheduleWindowBounds = {
  start: DAY_START, end: DAY_END,
  startMinutes: DAY_START_MINUTES, endMinutes: DAY_END_MINUTES,
}

export interface RenderBounds {
  renderStart: number
  renderEnd: number
}

export interface ScheduleDisplayItem {
  // "spacer" is a NON-INTERACTIVE flow-layout filler: geometry only, never a
  // clickable GapSlot. It occupies the region between an out-of-window legacy
  // block and the window so later items keep their correct vertical offset,
  // without offering an "add here" surface outside the window.
  type: "block" | "gap" | "block-with-now" | "gap-with-now" | "spacer"
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

export function clampToDay(minutes: number, window = DEFAULT_SCHEDULE_WINDOW): number {
  return Math.max(window.startMinutes, Math.min(window.endMinutes, minutes))
}

/**
 * Return structural items sorted by (start_time, optional sort_order). Values
 * are never dropped and the returned array is fresh, so callers' arrays
 * (including Inertia props) are never mutated in place. Missing sort_order
 * is treated as zero.
 */
export function sortBlocksByStart<T extends { start_time: string; sort_order?: number }>(
  blocks: T[],
): T[] {
  return [...blocks].sort((a, b) => {
    const startDelta = timeToMinutes(a.start_time) - timeToMinutes(b.start_time)
    return startDelta !== 0 ? startDelta : (a.sort_order ?? 0) - (b.sort_order ?? 0)
  })
}

/**
 * Trailing anchor shared by `computeRenderBounds` and `buildBaseDisplayItems`
 * — the two must produce identical anchors or flow layout desyncs from the
 * stub height. `anchorFloor` is `lastEnd` (≥1 visible block) or
 * `DAY_START_MINUTES` (empty day). `nowMinutes === null` means off-today →
 * exact 0017 anchor (`anchorFloor`). On today the anchor extends to `now` so
 * the idle gap after the last block renders at full scale; the outer
 * `DAY_END_MINUTES` clamp keeps a post-23:00 "now" from pushing the split
 * boundary past the day end.
 */
export function computeTrailingAnchor(
  anchorFloor: number,
  nowMinutes: number | null,
  window = DEFAULT_SCHEDULE_WINDOW,
): number {
  if (nowMinutes === null) return anchorFloor
  return Math.min(window.endMinutes, Math.max(anchorFloor, nowMinutes))
}

/**
 * Origin-shift linear render bounds for compact edge stubs. `nowMinutes` is
 * non-null only on today (callers pass `nowDate === null ? null : nowMinutes`)
 * — a non-null value unambiguously means "today" and makes the trailing
 * anchor now-aware; `null` (default) keeps exact 0017 behavior.
 */
export function computeRenderBounds(
  blocks: TimeBlock[],
  nowMinutes: number | null = null,
  window = DEFAULT_SCHEDULE_WINDOW,
): RenderBounds {
  const visible = blocks
    .filter((b) => timeToMinutes(b.end_time) > window.startMinutes && timeToMinutes(b.start_time) < window.endMinutes)
    .sort((a, b) => timeToMinutes(a.start_time) - timeToMinutes(b.start_time) || a.sort_order - b.sort_order)
  if (visible.length === 0) {
    // Empty window-overlapping subset. A truly empty day (no blocks at all)
    // renders the full window geometry (compressed tail on today). But when
    // blocks EXIST yet none overlaps the window, using the full window as the
    // base and then unioning the outside blocks blows the canvas out to
    // [windowStart, windowEnd] ∪ blocks. Instead, when every block is outside
    // the window, size the canvas to the blocks alone so a wholly-outside-only
    // day never spans the empty window.
    if (blocks.length === 0) {
      if (nowMinutes === null) {
        return { renderStart: window.startMinutes, renderEnd: window.endMinutes }
      }
      const trailingAnchor = computeTrailingAnchor(window.startMinutes, nowMinutes, window)
      return {
        renderStart: window.startMinutes,
        renderEnd: Math.min(window.endMinutes, trailingAnchor + STUB_MINUTES),
      }
    }
    // Blocks exist but none overlaps the window (e.g. a 06:00–07:00-only day
    // after narrowing to 08:00). Show the working window as the base — the user
    // still needs an in-window canvas to see/add slots — then union the
    // stranded outside blocks so they stay on-screen (a leading spacer bridges
    // the gap). Basing on the blocks alone would collapse the window to 0px.
    const windowEndBase =
      nowMinutes === null
        ? window.endMinutes
        : Math.min(
            window.endMinutes,
            computeTrailingAnchor(window.startMinutes, nowMinutes, window) +
              STUB_MINUTES,
          )
    return {
      renderStart: Math.min(
        window.startMinutes,
        ...blocks.map((b) => timeToMinutes(b.start_time)),
      ),
      renderEnd: Math.max(
        windowEndBase,
        ...blocks.map((b) => timeToMinutes(b.end_time)),
      ),
    }
  }

  const firstStart = Math.max(
    timeToMinutes(visible[0].start_time),
    window.startMinutes,
  )
  const lastEnd = Math.min(
    timeToMinutes(visible[visible.length - 1].end_time),
    window.endMinutes,
  )

  const leadingGap = firstStart - window.startMinutes
  // Compression threshold stays keyed off the REAL trailing gap from lastEnd
  // (0017): an already-natural trailing gap never compresses regardless of now.
  const trailingGap = window.endMinutes - lastEnd
  const trailingAnchor = computeTrailingAnchor(lastEnd, nowMinutes, window)

  const base = {
    renderStart:
      leadingGap > STUB_MINUTES ? firstStart - STUB_MINUTES : window.startMinutes,
    renderEnd:
      trailingGap > STUB_MINUTES
        ? Math.min(window.endMinutes, trailingAnchor + STUB_MINUTES)
        : window.endMinutes,
  }
  // Stored blocks always retain their true geometry. The compact/stub base
  // is calculated only from window-overlapping blocks, then expanded so
  // legacy blocks outside a newly narrowed window remain on-screen.
  return {
    renderStart: Math.min(base.renderStart, ...blocks.map((b) => timeToMinutes(b.start_time))),
    renderEnd: Math.max(base.renderEnd, ...blocks.map((b) => timeToMinutes(b.end_time))),
  }
}

/**
 * Emit the trailing gap `[gapStart, DAY_END)` onto `items`. On today with an
 * idle interval (`trailingAnchor > gapStart`) and a real compressed tail
 * (`activeRenderEnd < DAY_END_MINUTES`), split into a full-scale idle gap
 * `[gapStart, trailingAnchor)` plus a compact tail `[trailingAnchor, DAY_END)`.
 * The single gate covers both overflow edges: now ≥ 23:00 clamps
 * `activeRenderEnd` to `DAY_END` (gate false → single gap), and
 * `activeRenderEnd < DAY_END` implies `trailingAnchor < DAY_END` under the
 * bounds contract, so the idle segment never crosses 23:00. Otherwise emit the
 * single 0017 gap, compressed iff `activeRenderEnd < DAY_END_MINUTES`.
 */
function pushTrailingGap(
  items: ScheduleDisplayItem[],
  gapStart: number,
  activeRenderEnd: number,
  nowMinutes: number | null,
  window = DEFAULT_SCHEDULE_WINDOW,
): void {
  if (gapStart >= window.endMinutes) return

  const trailingAnchor = computeTrailingAnchor(gapStart, nowMinutes, window)
  if (trailingAnchor > gapStart && activeRenderEnd < window.endMinutes) {
    items.push({
      type: "gap",
      start_time: minutesToTime(gapStart),
      end_time: minutesToTime(trailingAnchor),
      duration_minutes: trailingAnchor - gapStart,
    })
    items.push({
      type: "gap",
      start_time: minutesToTime(trailingAnchor),
      end_time: window.end,
      duration_minutes: window.endMinutes - trailingAnchor,
      render_minutes: Math.max(0, activeRenderEnd - trailingAnchor),
      compact: true,
    })
    return
  }

  const compressed = activeRenderEnd < window.endMinutes
  items.push({
    type: "gap",
    start_time: minutesToTime(gapStart),
    end_time: window.end,
    duration_minutes: window.endMinutes - gapStart,
    ...(compressed
      ? {
          render_minutes: Math.max(0, activeRenderEnd - gapStart),
          compact: true,
        }
      : {}),
  })
}

/**
 * Emit the region `[gapStart, nextStart)` between two consecutive blocks, split
 * into up to three segments so no "add here" surface is offered outside the
 * window:
 *  - the part before `window.startMinutes` → inert `spacer`;
 *  - the in-window part `[window.startMinutes, window.endMinutes)` → clickable `gap`;
 *  - the part at/after `window.endMinutes` (e.g. before a late out-of-window
 *    legacy block) → inert `spacer`.
 * Spacers are non-interactive geometry that keep the following item at the
 * correct vertical offset. (The trailing gap after the LAST block is handled by
 * `pushTrailingGap`, which caps at `window.endMinutes`.)
 */
function pushInterBlockGap(
  items: ScheduleDisplayItem[],
  gapStart: number,
  nextStart: number,
  window = DEFAULT_SCHEDULE_WINDOW,
): void {
  if (nextStart <= gapStart) return

  // Region before the window start → inert spacer (out-of-window geometry).
  const leadEnd = Math.min(nextStart, window.startMinutes)
  if (leadEnd > gapStart) {
    items.push({
      type: "spacer",
      start_time: minutesToTime(gapStart),
      end_time: minutesToTime(leadEnd),
      duration_minutes: leadEnd - gapStart,
    })
  }

  // In-window remainder → clickable gap, capped at the window end.
  const clickStart = Math.max(gapStart, window.startMinutes)
  const clickEnd = Math.min(nextStart, window.endMinutes)
  if (clickEnd > clickStart) {
    items.push({
      type: "gap",
      start_time: minutesToTime(clickStart),
      end_time: minutesToTime(clickEnd),
      duration_minutes: clickEnd - clickStart,
    })
  }

  // Region at/after the window end → inert spacer (out-of-window geometry).
  const trailStart = Math.max(gapStart, window.endMinutes)
  if (nextStart > trailStart) {
    items.push({
      type: "spacer",
      start_time: minutesToTime(trailStart),
      end_time: minutesToTime(nextStart),
      duration_minutes: nextStart - trailStart,
    })
  }
}

/**
 * Build the block/gap list before now-marker splicing. Edge gaps may
 * compress to stub height; `activeRender*` is frozen during drag.
 * `nowMinutes` is non-null only on today (same contract as
 * `computeRenderBounds`) and splits the trailing gap into a full-scale idle
 * segment `[lastEnd, now)` plus a compressed tail — `null` (default) keeps
 * exact 0017 behavior.
 */
export function buildBaseDisplayItems(
  blocks: TimeBlock[],
  activeRenderStart: number,
  activeRenderEnd: number,
  nowMinutes: number | null = null,
  window = DEFAULT_SCHEDULE_WINDOW,
): ScheduleDisplayItem[] {
  const items: ScheduleDisplayItem[] = []
  const visibleBlocks = sortBlocksByStart(blocks)

  if (visibleBlocks.length === 0) {
    pushTrailingGap(items, window.startMinutes, activeRenderEnd, nowMinutes, window)
    return items
  }

  // A leading GAP only exists when the first item that reaches the window
  // starts after the window start AND no block sits before the window. An
  // out-of-window early block (start < windowStart) renders at true geometry
  // first, then the flow-layout emits an inert spacer up to the window (below).
  const firstBlockStart = timeToMinutes(visibleBlocks[0].start_time)
  const firstStart = Math.max(firstBlockStart, window.startMinutes)
  if (firstBlockStart >= window.startMinutes && firstStart > window.startMinutes) {
    // Cap the clickable leading gap at the window end — a late-only first block
    // (e.g. 22:00 under an 08:00–20:00 window) must not offer an "add here"
    // surface past the window end; the overflow becomes an inert spacer.
    const gapEnd = Math.min(firstStart, window.endMinutes)
    if (gapEnd > window.startMinutes) {
      const compressed = activeRenderStart > window.startMinutes
      items.push({
        type: "gap",
        start_time: window.start,
        end_time: minutesToTime(gapEnd),
        duration_minutes: gapEnd - window.startMinutes,
        ...(compressed
          ? {
              render_minutes: Math.max(0, gapEnd - activeRenderStart),
              compact: true,
            }
          : {}),
      })
    }
    // Out-of-window remainder before a late-only first block → inert spacer.
    if (firstStart > window.endMinutes) {
      items.push({
        type: "spacer",
        start_time: window.end,
        end_time: minutesToTime(firstStart),
        duration_minutes: firstStart - window.endMinutes,
      })
    }
  }

  for (let i = 0; i < visibleBlocks.length; i++) {
    const block = visibleBlocks[i]
    const blockStart = timeToMinutes(block.start_time)
    const blockEnd = timeToMinutes(block.end_time)
    items.push({
      type: "block",
      block,
      start_time: minutesToTime(blockStart),
      end_time: minutesToTime(blockEnd),
      duration_minutes: blockEnd - blockStart,
    })

    if (i < visibleBlocks.length - 1) {
      const gapStart = blockEnd
      const nextBlockStart = timeToMinutes(visibleBlocks[i + 1].start_time)
      pushInterBlockGap(items, gapStart, nextBlockStart, window)
    }
  }

  const lastEnd = timeToMinutes(visibleBlocks[visibleBlocks.length - 1].end_time)
  // If the last block ends before the window start (an early-only out-of-window
  // day, e.g. a lone 06:00–07:00 block under 08:00–20:00), the pre-window
  // remainder is an inert spacer; the clickable trailing gap begins at the
  // window start so no "add here" surface is offered outside the window.
  if (lastEnd < window.startMinutes) {
    items.push({
      type: "spacer",
      start_time: minutesToTime(lastEnd),
      end_time: window.start,
      duration_minutes: window.startMinutes - lastEnd,
    })
  }
  pushTrailingGap(
    items,
    Math.max(lastEnd, window.startMinutes),
    activeRenderEnd,
    nowMinutes,
    window,
  )

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

    // A `spacer` is inert out-of-window geometry with no `block`; retagging it
    // to `block-with-now` would make the template render nothing (it requires
    // `item.block`), dropping the spacer height and the NowLine. Leave spacers
    // untouched — the pre-window zone is outside the working day, so no marker.
    if (inserted || nowMinutes < start || nowMinutes >= end || item.type === "spacer") {
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
 * when `nowMinutes` is `null` (off-today) or the span is non-positive. The
 * result is clamped to `[0, 100]%` defensively — callers only splice the now
 * marker into the containing item, but clamping prevents an out-of-range CSS
 * `top` if that invariant ever breaks.
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
  const pct = ((nowMinutes - start) / span) * 100
  return Math.max(0, Math.min(100, pct)) + "%"
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
