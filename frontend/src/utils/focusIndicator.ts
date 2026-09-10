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

/** The bounds of the current pause, in minutes-of-day. */
export interface PauseWindow {
  /**
   * The end of the last block that has already ended, or `null` before the
   * day's first block — nothing has ended yet, so an elapsed-pause fraction
   * has no honest origin to measure from.
   */
  startMinutes: number | null
  endMinutes: number
}

/**
 * The gap the focus indicator is currently sitting in: from the latest already
 * ended block to the start of the next one (feature 0079).
 *
 * `null` means there is no measurable pause at all — off-today, no block starts
 * after now (see `isDayFinished`), or any `end_time` is unparseable. Malformed
 * data fails closed rather than inventing a window, matching `nextBlockAfter`.
 */
export function pauseWindow(
  blocks: TimeBlock[],
  nowMinutes: number | null,
  nowDate: string | null,
): PauseWindow | null {
  const next = nextBlockAfter(blocks, nowMinutes, nowDate)
  if (next === null || nowMinutes === null) return null

  const ends = blocks.map((block) => timeToMinutes(block.end_time))
  if (ends.some((end) => !Number.isFinite(end))) return null

  // A block ending exactly now is the pause origin; one still running is not.
  const ended = ends.filter((end) => end <= nowMinutes)
  return {
    startMinutes: ended.length > 0 ? Math.max(...ended) : null,
    endMinutes: timeToMinutes(next.start_time),
  }
}

/**
 * Elapsed fraction of `pause` at `nowMinutes`, clamped to `[0, 1]`. `null`
 * (caller renders a dashed track with no fill) when the pause has no origin,
 * no now-signal, or a non-positive duration. Mirrors `progressRatio`, which
 * does the same for an active block.
 */
export function pauseProgressRatio(
  pause: PauseWindow | null,
  nowMinutes: number | null,
): number | null {
  if (pause === null || pause.startMinutes === null || nowMinutes === null) return null
  const duration = pause.endMinutes - pause.startMinutes
  if (!Number.isFinite(duration) || duration <= 0) return null
  return Math.max(0, Math.min(1, (nowMinutes - pause.startMinutes) / duration))
}

/**
 * Whether today's schedule is spent: every block has ended. Drives the PiP's
 * `Pause · day finished` body.
 *
 * Deliberately stricter than "no block starts after now": an empty day, a
 * still-running block (even a completed one), unparseable times and inverted
 * blocks all return `false` so the window falls back to the neutral state
 * instead of claiming a finished day it cannot prove.
 */
export function isDayFinished(
  blocks: TimeBlock[],
  nowMinutes: number | null,
  nowDate: string | null,
): boolean {
  // `nowDate` is null exactly when the retained date is not today (the
  // `useNowMinutes` contract), so this doubles as the off-today guard — another
  // day is never "finished". Its value is deliberately never read.
  if (nowMinutes === null || nowDate === null || blocks.length === 0) return false
  return blocks.every((block) => {
    const start = timeToMinutes(block.start_time)
    const end = timeToMinutes(block.end_time)
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return false
    return end <= nowMinutes
  })
}
