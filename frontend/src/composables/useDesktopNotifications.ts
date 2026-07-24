import { ref } from "vue"
import type { Ref } from "vue"
import type { SoundEventType, TimeBlock } from "../types"
import {
  readDesktopNotificationsEnabled,
  writeDesktopNotificationsEnabled,
} from "../utils/desktopNotificationStorage"
import {
  desktopNotificationBody,
  desktopNotificationTitle,
} from "../utils/desktopNotificationCopy"
import { useBlockBoundaryDetector } from "./useBlockBoundaryDetector"

// Desktop-notification channel for block start/end boundaries (issue #100 /
// feature 0028). Opt-in, default off, persisted per-device in localStorage.
// Reuses the shared `useBlockBoundaryDetector` — no second interval. Only
// fires while the Schedule page is mounted (foreground OR background tab);
// no Service Worker / closed-tab alerts. Independent of the sound channel.

/**
 * Owns the opt-in `enabled` flag + permission handling. Consumed by the
 * Settings toggle (presentational) and, internally, by the detector below.
 *
 * `permissionDenied` drives the "browser blocked it" hint; `notSupported`
 * drives the distinct "this browser has no Notification API" hint — two
 * separate flags because the copy differs and a bare boolean cannot carry
 * both messages (never show "allow in site settings" for a browser that has
 * no notification support at all).
 */
export function useDesktopNotificationSetting(): {
  enabled: Ref<boolean>
  setEnabled: (v: boolean) => Promise<void>
  permissionDenied: Ref<boolean>
  notSupported: Ref<boolean>
} {
  const enabled = ref(false)
  const permissionDenied = ref(false)
  // Support is immutable per page load — initialised unconditionally at setup,
  // independent of any stored flag, so an unsupported browser shows the
  // disabled switch + "doesn't support" hint on first render even with an
  // absent/false storage value. Never recomputed or cleared afterward.
  const notSupported = ref(typeof Notification === "undefined")

  // Monotonic request token: every setEnabled call bumps it so a late
  // requestPermission() continuation can detect it was superseded.
  let requestSeq = 0

  // Mount init: read the persisted flag AND re-validate runtime permission.
  if (typeof Notification === "undefined") {
    // Non-supporting browser: a hand-edited storage `true` must resolve to off
    // WITHOUT dereferencing Notification.permission (which would throw), and
    // must clear the stale flag so no phantom `true` key survives.
    if (readDesktopNotificationsEnabled()) writeDesktopNotificationsEnabled(false)
    enabled.value = false
  } else if (readDesktopNotificationsEnabled()) {
    if (Notification.permission === "granted") {
      enabled.value = true
    } else {
      // Storage says on but the user revoked permission in browser settings:
      // treat as off and clear the stale flag.
      writeDesktopNotificationsEnabled(false)
      enabled.value = false
    }
  }

  async function setEnabled(v: boolean): Promise<void> {
    if (v === false) {
      // Bump the token first so any in-flight setEnabled(true) continuation
      // sees itself superseded and returns without touching state.
      ++requestSeq
      writeDesktopNotificationsEnabled(false)
      enabled.value = false
      permissionDenied.value = false
      return
    }

    const token = ++requestSeq

    if (typeof Notification === "undefined") {
      // notSupported is already true from the unconditional setup init (support
      // is immutable per page load) — no reassignment needed here.
      enabled.value = false
      permissionDenied.value = false
      return
    }

    let result: NotificationPermission
    try {
      result = await Notification.requestPermission()
    } catch {
      // Legacy callback-form / hardened browsers can reject or throw — treat
      // exactly like a denial, never leave it as an unhandled rejection.
      result = "denied"
    }

    // Stale-request guard (mandatory) — check FIRST, unconditionally. A newer
    // setEnabled call superseded this one: return without touching storage,
    // `enabled`, or `permissionDenied` so a late grant/denial cannot resurrect
    // `true` OR stamp a spurious "blocked" hint on a checkbox the user turned
    // off. Must be its own early return, NOT folded into the branches below.
    if (token !== requestSeq) return

    if (result === "granted") {
      writeDesktopNotificationsEnabled(true)
      enabled.value = true
      permissionDenied.value = false
    } else {
      // denied / default: do not persist true.
      enabled.value = false
      permissionDenied.value = true
    }
  }

  return { enabled, setEnabled, permissionDenied, notSupported }
}

/**
 * Build + show a single desktop notification for a crossed boundary. Fully
 * guarded — never throws into the Schedule render path.
 */
export function showDesktopNotification(
  type: SoundEventType,
  block: TimeBlock,
  date: string,
  boundaryMinutes: number,
): void {
  if (typeof Notification === "undefined") return
  if (Notification.permission !== "granted") return
  try {
    const n = new Notification(desktopNotificationTitle(type), {
      body: desktopNotificationBody(type, block),
      // Tag dedupes OS-level stacking for the same boundary (belt-and-
      // suspenders on top of the detector's in-memory `fired` Set). The tag
      // embeds `boundaryMinutes` to stay aligned with the detector's fired key
      // — a re-timed block re-fires via a new fired key, so its OS tag must
      // also differ or the OS would coalesce it under the old minute's tag.
      tag: `day-forge:${type}:${block.id}:${date}:${boundaryMinutes}`,
    })
    n.onclick = () => {
      // Guard window.focus() — it can throw in a sandboxed iframe / hardened
      // browser; a throw here would surface as an unhandled error from the OS
      // click callback. Same swallow policy as the construction path.
      try {
        window.focus()
      } catch {
        // ignore — best-effort focus
      }
      n.close()
    }
  } catch {
    // never break the schedule UI on a Notification construction error
  }
}

/**
 * Detector wiring for the desktop channel. Same arity as
 * `useSoundNotifications`. Only shows when `enabled` AND permission granted
 * (the detector `enabled` ref covers the setting; `showDesktopNotification`
 * double-checks permission at fire time).
 *
 * @param nowMinutes minutes-since-midnight (or null off-today) from useNowMinutes
 * @param nowDate    "YYYY-MM-DD" (or null off-today) from useNowMinutes
 * @param getBlocks  getter over the live block list (avoids stale capture)
 */
export function useDesktopNotifications(
  nowMinutes: Ref<number | null>,
  nowDate: Ref<string | null>,
  getBlocks: () => TimeBlock[],
): {
  enabled: Ref<boolean>
  setEnabled: (v: boolean) => Promise<void>
  permissionDenied: Ref<boolean>
  notSupported: Ref<boolean>
} {
  const { enabled, setEnabled, permissionDenied, notSupported } =
    useDesktopNotificationSetting()

  useBlockBoundaryDetector(nowMinutes, nowDate, getBlocks, {
    enabled,
    onBoundary: ({ type, block, date, boundaryMinutes }) =>
      showDesktopNotification(type, block, date, boundaryMinutes),
  })

  return { enabled, setEnabled, permissionDenied, notSupported }
}
