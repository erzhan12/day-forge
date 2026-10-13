import { onUnmounted, ref, watch } from "vue"
import type { Ref } from "vue"
import { zonedDateTime } from "../utils/date"

const NOW_UPDATE_INTERVAL_MS = 60_000
// Hidden-tab gaps still pass through useBlockBoundaryDetector's bounded
// crossing logic. A visibility sample updates the displayed date promptly.

/**
 * Centralised 60s current-time sampler for schedule UI.
 *
 * `todayDate` always tracks the saved zone. Clock refs are populated only
 * while the viewed date is today in that zone. The timer stays armed while
 * off-today, allowing a future date to become today at midnight.
 */
export function useNowMinutes(viewedDate: Ref<string>, timeZone: Ref<string>) {
  const nowMinutes = ref<number | null>(null)
  const nowDate = ref<string | null>(null)
  const currentHHMM = ref("")
  const todayDate = ref("")

  function tick() {
    const sample = zonedDateTime(new Date(), timeZone.value)
    todayDate.value = sample.date
    if (viewedDate.value !== sample.date) {
      nowMinutes.value = null
      nowDate.value = null
      currentHHMM.value = ""
      return
    }
    nowMinutes.value = sample.minutes
    nowDate.value = sample.date
    currentHHMM.value = sample.hhmm
  }

  watch([viewedDate, timeZone], tick, { immediate: true, flush: "sync" })
  const interval = setInterval(tick, NOW_UPDATE_INTERVAL_MS)
  const onVisible = () => {
    if (document.visibilityState === "visible") tick()
  }
  document.addEventListener("visibilitychange", onVisible)

  onUnmounted(() => {
    clearInterval(interval)
    document.removeEventListener("visibilitychange", onVisible)
  })

  return { nowMinutes, nowDate, currentHHMM, todayDate }
}
