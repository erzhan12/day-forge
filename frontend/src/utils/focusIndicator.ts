import type { TimeBlock } from "../types"
import { findCurrentBlock, timeToMinutes } from "./scheduleTime"

/**
 * The focus indicator's active block: the current-minute block per
 * `findCurrentBlock` (half-open `[start, end)`, overlap winner by
 * `(start_time, sort_order)`) that is **not** completed.
 *
 * Guards `null` `nowMinutes` / `nowDate` (off-today) BEFORE delegating —
 * `findCurrentBlock` types `nowMinutes` non-null and a raw pass-through would
 * coerce `null` to `0` and match a 00:00 block (see 0049 plan § Null-guard).
 */
export function activeUnfinishedBlock(
  blocks: TimeBlock[],
  nowMinutes: number | null,
  nowDate: string | null,
): TimeBlock | null {
  if (nowMinutes === null || nowDate === null) return null
  const current = findCurrentBlock(blocks, nowMinutes, nowDate)
  if (current === null || current.is_completed) return null
  return current
}

/**
 * The nearest block starting strictly after `nowMinutes`, for today's idle
 * focus-indicator state. A null today signal or one malformed start anywhere
 * fails closed: without every start, the chronological "nearest" claim cannot
 * be proved. Equal starts use `sort_order`; the selected candidate must itself
 * have a finite, positive duration and is never skipped for a later block.
 */
export function nextBlockAfter(
  blocks: TimeBlock[],
  nowMinutes: number | null,
  nowDate: string | null,
): TimeBlock | null {
  if (nowMinutes === null || nowDate === null) return null

  const withStarts = blocks.map((block) => ({ block, start: timeToMinutes(block.start_time) }))
  if (withStarts.some(({ start }) => !Number.isFinite(start))) return null

  const next = withStarts
    .filter(({ start }) => start > nowMinutes)
    .sort((a, b) => a.start - b.start || a.block.sort_order - b.block.sort_order)[0]
  if (!next) return null

  const end = timeToMinutes(next.block.end_time)
  const duration = end - next.start
  if (!Number.isFinite(duration) || duration <= 0) return null
  return next.block
}

/**
 * Elapsed fraction of `block` at `nowMinutes`, clamped to `[0, 1]`. Returns
 * `null` (caller renders neutral, never NaN/Infinity) when the duration is
 * zero, negative, or unparseable — fail closed per the 0049 plan.
 */
export function progressRatio(block: TimeBlock, nowMinutes: number): number | null {
  const start = timeToMinutes(block.start_time)
  const end = timeToMinutes(block.end_time)
  const duration = end - start
  if (!Number.isFinite(duration) || duration <= 0) return null
  const ratio = (nowMinutes - start) / duration
  return Math.max(0, Math.min(1, ratio))
}

/** Integer percent for a progress ratio; `0` for a `null` (neutral) ratio. */
export function progressPercentFromRatio(ratio: number | null): number {
  return ratio === null ? 0 : Math.round(ratio * 100)
}
