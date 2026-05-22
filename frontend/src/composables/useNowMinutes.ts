import { onUnmounted, ref, watch } from "vue"
import type { Ref } from "vue"
import { todayString } from "../utils/date"

const NOW_UPDATE_INTERVAL_MS = 60_000

function sampleNow(): { minutes: number; hhmm: string } {
  const now = new Date()
  const hours = now.getHours()
  const minutes = now.getMinutes()
  return {
    minutes: hours * 60 + minutes,
    hhmm: `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`,
  }
}

export function useNowMinutes(viewedDate: Ref<string>) {
  const nowMinutes = ref<number | null>(null)
  const nowDate = ref<string | null>(null)
  const currentHHMM = ref("")
  let interval: ReturnType<typeof setInterval> | null = null

  function clearTimer() {
    if (interval !== null) {
      clearInterval(interval)
      interval = null
    }
  }

  function leaveToday() {
    clearTimer()
    nowMinutes.value = null
    nowDate.value = null
    currentHHMM.value = ""
  }

  function enterToday(today: string) {
    clearTimer()
    const sample = sampleNow()
    nowMinutes.value = sample.minutes
    nowDate.value = today
    currentHHMM.value = sample.hhmm
    interval = setInterval(tick, NOW_UPDATE_INTERVAL_MS)
  }

  function syncToViewedDate() {
    const today = todayString()
    if (viewedDate.value === today) {
      enterToday(today)
    } else {
      leaveToday()
    }
  }

  function tick() {
    const today = todayString()
    if (viewedDate.value !== today) {
      leaveToday()
      return
    }

    const sample = sampleNow()
    nowMinutes.value = sample.minutes
    nowDate.value = today
    currentHHMM.value = sample.hhmm
  }

  watch(viewedDate, syncToViewedDate, { immediate: true })

  onUnmounted(() => {
    clearTimer()
  })

  return { nowMinutes, nowDate, currentHHMM }
}
