import { watch } from "vue"
import type { Ref } from "vue"
import type { SoundEventType, TimeBlock } from "../types"
import { timeToMinutes } from "../utils/scheduleTime"

// Shared boundary-cross detector for block start/end times (issue #56 / #100).
// Extracted verbatim-in-behaviour from useSoundNotifications.ts so that both
// the sound (feature 0019) and desktop-notification (feature 0028) channels
// drive the SAME crossed-since-last-sample state machine. Each consumer calls
// this with its own `enabled` ref + `onBoundary` callback, so the two channels
// keep independent `lastSeenMinute`/`fired` cursors — disabling one does not
// advance the other. Piggybacks the existing 60s `useNowMinutes` sampler; it
// does NOT create its own interval.
//
// The detector works in integer minutes-since-midnight so the
// crossed-since-last-sample window is plain arithmetic. `timeToMinutes` is the
// canonical "HH:MM" → minutes converter used across the schedule code.

export interface BoundaryEvent {
  type: SoundEventType
  block: TimeBlock
  date: string
  boundaryMinutes: number
}

/**
 * @param nowMinutes minutes-since-midnight (or null off-today) from useNowMinutes
 * @param nowDate    "YYYY-MM-DD" (or null off-today) from useNowMinutes
 * @param getBlocks  getter over the live block list (avoids stale capture)
 * @param options    `enabled` opt-in ref + `onBoundary` side-effect callback
 */
export function useBlockBoundaryDetector(
  nowMinutes: Ref<number | null>,
  nowDate: Ref<string | null>,
  getBlocks: () => TimeBlock[],
  options: {
    enabled: Ref<boolean>
    onBoundary: (event: BoundaryEvent) => void
  },
): void {
  const { enabled, onBoundary } = options

  // Last minute observed for the current date; null before the first tick of
  // a date (and after a reset). Drives the crossed-since-last-sample window.
  let lastSeenMinute: number | null = null
  // Idempotent guard keyed by `${type}:${blockId}:${date}:${boundaryMinute}`.
  // Belt-and-suspenders on top of the window so a boundary cannot fire twice
  // for the same block on the same day.
  const fired = new Set<string>()

  // Reset on date change. The ONLY real reset trigger is explicit date
  // navigation — useNowMinutes leaves-today on midnight rollover and does NOT
  // re-arm its timer, so a tab open across midnight simply stops firing until
  // the user navigates (documented limitation, 0019_PLAN.md).
  watch(nowDate, () => {
    fired.clear()
    lastSeenMinute = null
  })

  // Treat enabling as a fresh first tick: clear lastSeenMinute so toggling on
  // does NOT back-fire every boundary that passed while the setting was off
  // (the window (prev, now] would otherwise span the disabled period).
  watch(enabled, (on) => {
    if (on) lastSeenMinute = null
  })

  watch(nowMinutes, () => {
    // Step 1: primary suppression gate. First so a disabled setting short-
    // circuits before any block work AND without advancing lastSeenMinute.
    if (!enabled.value) return

    // Step 2: off-today guard. useNowMinutes nulls both off-today, so no
    // future/past-date block ever fires.
    const now = nowMinutes.value
    const date = nowDate.value
    if (now === null || date === null) return

    const prev = lastSeenMinute

    // Eligible-window predicate:
    //  - first tick of a date (prev === null): only boundaries exactly at
    //    `now` — never back-fill the whole day from midnight.
    //  - backward step (now <= prev, e.g. DST fall-back / manual clock
    //    change): fire nothing; just resync lastSeenMinute below.
    //  - normal/coalesced forward tick: half-open interval (prev, now].
    const inWindow = (boundary: number): boolean => {
      if (prev === null) return boundary === now
      if (now <= prev) return false
      return boundary > prev && boundary <= now
    }

    for (const block of getBlocks()) {
      const s = timeToMinutes(block.start_time)
      const e = timeToMinutes(block.end_time)
      // Key includes the boundary minute so re-timing a block (an edit, or a
      // drag that shifts its time) after the old boundary already fired still
      // fires the NEW boundary; a stationary re-flow at the same minute still
      // self-dedupes. Bounded — `fired` is cleared on date change.
      const startKey = `start:${block.id}:${date}:${s}`
      const endKey = `end:${block.id}:${date}:${e}`
      if (inWindow(s) && !fired.has(startKey)) {
        onBoundary({ type: "start", block, date, boundaryMinutes: s })
        fired.add(startKey)
      }
      if (inWindow(e) && !fired.has(endKey)) {
        onBoundary({ type: "end", block, date, boundaryMinutes: e })
        fired.add(endKey)
      }
    }

    lastSeenMinute = now
  })
}
