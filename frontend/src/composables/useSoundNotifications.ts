import { ref } from "vue"
import type { Ref } from "vue"
import type { SoundEventType, TimeBlock } from "../types"
import {
  readSoundNotificationsEnabled,
  writeSoundNotificationsEnabled,
} from "../utils/soundNotificationStorage"
import { getAudioContext, unlockAudioContext } from "../utils/audioContext"
import { useBlockBoundaryDetector } from "./useBlockBoundaryDetector"

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
 * interval. Delegates the crossed-since-last-sample state machine to the
 * shared `useBlockBoundaryDetector` (feature 0028), passing its own `enabled`
 * ref and a `playSound` callback so the sound channel keeps an independent
 * cursor from the desktop-notification channel.
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

  useBlockBoundaryDetector(nowMinutes, nowDate, getBlocks, {
    enabled,
    onBoundary: ({ type }) => playSound(type),
  })

  return { enabled, setEnabled }
}
