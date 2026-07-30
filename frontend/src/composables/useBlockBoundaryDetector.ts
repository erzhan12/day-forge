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
// The `nowMinutes` watch uses `{ immediate: true }` so registration with
// pre-populated refs (Schedule samples wall clock via useNowMinutes before
// this detector mounts) is treated as a first tick with exact-`now` matching
// — fires a boundary that equals the current minute, but never replays earlier
// same-day boundaries (issue #113 / feature 0029).
//
// Suspension-gap clamp (issue #112 / feature 0033): a same-day forward jump
// above MAX_COALESCE_GAP_MINUTES clamps the eligible window to
// `(now - MAX_COALESCE_GAP_MINUTES, now]` so multi-hour device-sleep /
// lunch-break resumes do not replay every stale boundary in `(prev, now]`.
// Modest coalescing (delta ≤ horizon) and normal cadence keep the full
// `(prev, now]` replay. Rejected alternative: a `visibilitychange` listener
// — the clamp is a pure function of the gap the detector already observes,
// and a listener would race the resume tick; resume delivery can still wait
// up to one sampler period (NOW_UPDATE_INTERVAL_MS) which is delivery latency,
// not a dropped recent boundary (those stay inside the clamped window).
//
// The detector works in integer minutes-since-midnight so the
// crossed-since-last-sample window is plain arithmetic. `timeToMinutes` is the
// canonical "HH:MM" → minutes converter used across the schedule code.

// Boundary-staleness horizon (feature 0033 / issue #112). On any sample,
// boundaries at or older than this many minutes (age ≥ N, i.e. at or before
// `now - N`) are treated as stale and not fired. Chosen > test #7's 4-minute
// coalesced jump so feature 0019's modest-coalescing contract stays on the
// full `(prev, now]` replay path; multi-hour same-day suspension resumes
// clamp to `(now - N, now]`.
const MAX_COALESCE_GAP_MINUTES = 5

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

  // `{ immediate: true }` so a pre-populated `nowMinutes` (Schedule mounts
  // `useNowMinutes` before this detector) is evaluated as the first tick —
  // otherwise the open-at-boundary minute is skipped until the next sampler
  // tick ~60s later (issue #113 / feature 0029). Same body; no second path.
  watch(
    nowMinutes,
    () => {
      // Step 1: primary suppression gate. First so a disabled setting short-
      // circuits before any block work AND without advancing lastSeenMinute.
      if (!enabled.value) return

      // Step 2: off-today guard. useNowMinutes nulls both off-today, so no
      // future/past-date block ever fires.
      const now = nowMinutes.value
      const date = nowDate.value
      if (now === null || date === null) return

      const prev = lastSeenMinute
      // Clamp the window start on a large same-day forward jump so a multi-
      // hour suspension resume only fires last-N-minute boundaries (issue
      // #112). When prev === null (first tick / enable-toggle) or the gap is
      // within the horizon, effectivePrev === prev and behaviour is unchanged.
      // lastSeenMinute itself is never mutated here — still assigned `= now`
      // at the end of the body. The fired Set is not cleared (date-scoped
      // idempotency; a same-day gap must not resurrect already-fired keys).
      const effectivePrev =
        prev === null ? null : Math.max(prev, now - MAX_COALESCE_GAP_MINUTES)

      // Eligible-window predicate:
      //  - first sample for this cursor (effectivePrev === null), including
      //    registration with pre-populated refs: only boundaries exactly at
      //    `now` — never back-fill earlier same-day boundaries.
      //  - backward step (now <= effectivePrev, e.g. DST fall-back / manual
      //    clock change): fire nothing; just resync lastSeenMinute below.
      //  - normal / modest-coalesced forward tick
      //    (now - prev <= MAX_COALESCE_GAP_MINUTES): half-open (prev, now]
      //    — effectivePrev === prev, full replay of leapt boundaries.
      //  - suspension resume (now - prev > MAX_COALESCE_GAP_MINUTES): clamped
      //    half-open (now - MAX_COALESCE_GAP_MINUTES, now] — only last-N-
      //    minute boundaries fire; multi-hour burst suppressed (issue #112).
      //    No visibilitychange listener: the clamp is sufficient for burst
      //    suppression; resume sample still waits for the next useNowMinutes
      //    tick (≤ one sampler period of delivery latency).
      const inWindow = (boundary: number): boolean => {
        if (effectivePrev === null) return boundary === now
        if (now <= effectivePrev) return false
        return boundary > effectivePrev && boundary <= now
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
    },
    { immediate: true },
  )
}
