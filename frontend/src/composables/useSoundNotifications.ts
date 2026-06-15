import { ref, watch } from "vue"
import type { Ref } from "vue"
import type { SoundEventType, TimeBlock } from "../types"
import {
  readSoundNotificationsEnabled,
  writeSoundNotificationsEnabled,
} from "../utils/soundNotificationStorage"
import { getAudioContext, unlockAudioContext } from "../utils/audioContext"
import { timeToMinutes } from "../utils/scheduleTime"

// The detector works in integer minutes-since-midnight so the
// crossed-since-last-sample window is plain arithmetic. `timeToMinutes` is
// the canonical "HH:MM" → minutes converter used across the schedule code.

// Two-note chime envelopes (~360ms total). Start rises (lower→higher),
// end falls (higher→lower) so the two events are audibly distinct.
const NOTE_DURATION_S = 0.18
const PEAK_GAIN = 0.15
const FREQS: Record<SoundEventType, [number, number]> = {
  start: [660, 880], // rising
  end: [880, 660], // falling
}

/**
 * Synthesize and play a short two-note chime for the given event. Pulls the
 * shared singleton AudioContext (resumed defensively in case this is a
 * brand-new session where the persisted flag is on but no gesture has
 * occurred yet). Fully try/catch-guarded — a flaky audio stack must never
 * throw into the schedule render path.
 */
function playSound(type: SoundEventType): void {
  try {
    const ctx = getAudioContext()
    if (ctx === null) return
    // Defensive resume: no-op if already running. Covers the only remaining
    // suspended-on-arrival case (fresh session, persisted flag true, no
    // gesture yet); the browser may still drop this first tone.
    void ctx.resume().catch(() => {})

    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)

    const t0 = ctx.currentTime
    const total = NOTE_DURATION_S * 2
    const [f1, f2] = FREQS[type]
    osc.frequency.setValueAtTime(f1, t0)
    osc.frequency.setValueAtTime(f2, t0 + NOTE_DURATION_S)

    // Click-free envelope: quick attack, exponential decay to near-zero.
    gain.gain.setValueAtTime(0.0001, t0)
    gain.gain.linearRampToValueAtTime(PEAK_GAIN, t0 + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + total)

    osc.start(t0)
    osc.stop(t0 + total)
  } catch {
    // never break the schedule UI on an audio error
  }
}

/**
 * Owns the opt-in `enabled` flag + its localStorage write. Consumed by the
 * Settings toggle (presentational) and, internally, by the detector below.
 * `setEnabled(true)` unlocks the shared AudioContext from inside the click
 * gesture so the Schedule detector plays through an already-running context.
 */
export function useSoundNotificationSetting(): {
  enabled: Ref<boolean>
  setEnabled: (v: boolean) => void
} {
  const enabled = ref(readSoundNotificationsEnabled())

  function setEnabled(v: boolean): void {
    writeSoundNotificationsEnabled(v)
    enabled.value = v
    if (v) unlockAudioContext()
  }

  return { enabled, setEnabled }
}

/**
 * Boundary-cross detector for block start/end times (issue #56). Piggybacks
 * the existing 60s `useNowMinutes` sampler — it does NOT create its own
 * interval. Fires a chime for every block boundary crossed since the last
 * observed minute, so a throttled/coalesced background-tab tick that skips
 * minutes still fires each boundary it leapt over.
 *
 * @param nowMinutes minutes-since-midnight (or null off-today) from useNowMinutes
 * @param nowDate    "YYYY-MM-DD" (or null off-today) from useNowMinutes
 * @param getBlocks  getter over the live block list (avoids stale capture)
 */
export function useSoundNotifications(
  nowMinutes: Ref<number | null>,
  nowDate: Ref<string | null>,
  getBlocks: () => TimeBlock[],
): { enabled: Ref<boolean>; setEnabled: (v: boolean) => void } {
  const { enabled, setEnabled } = useSoundNotificationSetting()

  // Last minute observed for the current date; null before the first tick of
  // a date (and after a reset). Drives the crossed-since-last-sample window.
  let lastSeenMinute: number | null = null
  // Idempotent guard keyed by `${type}:${blockId}:${date}`. Belt-and-
  // suspenders on top of the window so a boundary cannot fire twice for the
  // same block on the same day.
  const fired = new Set<string>()

  // Reset on date change. The ONLY real reset trigger is explicit date
  // navigation — useNowMinutes leaves-today on midnight rollover and does
  // NOT re-arm its timer, so a tab open across midnight simply stops firing
  // until the user navigates (documented limitation, 0019_PLAN.md).
  watch(nowDate, () => {
    fired.clear()
    lastSeenMinute = null
  })

  // Treat enabling as a fresh first tick: clear lastSeenMinute so toggling
  // on does NOT back-fire every boundary that passed while the setting was
  // off (the window (prev, now] would otherwise span the disabled period).
  // Same-instance safety net: the production wiring enables via the Settings
  // page (a separate detector instance) + remount, so this fires only if a
  // future caller toggles the setting on the same mounted detector.
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
        playSound("start")
        fired.add(startKey)
      }
      if (inWindow(e) && !fired.has(endKey)) {
        playSound("end")
        fired.add(endKey)
      }
    }

    lastSeenMinute = now
  })

  return { enabled, setEnabled }
}
