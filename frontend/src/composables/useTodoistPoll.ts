// Background Todoist refresh while the sidebar is open (feature 0021 / #71).
// Reuses `refreshTasks` (`?refresh=1`, silent) on a fixed interval. Pauses
// ticks while the tab is hidden; refreshes once when the tab becomes visible.

import { onBeforeUnmount, watch, type Ref } from "vue"

export interface TodoistPollOptions {
  intervalSeconds: Ref<number>
  date: Ref<string>
  active: Ref<boolean>
  refresh: (date: string) => void | Promise<void>
}

export function useTodoistPoll(options: TodoistPollOptions): void {
  let timer: ReturnType<typeof setInterval> | null = null

  function clearTimer(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function shouldPoll(): boolean {
    return options.active.value && options.intervalSeconds.value > 0
  }

  function pollOnce(): void {
    if (typeof document !== "undefined" && document.hidden) return
    if (!shouldPoll()) return
    void options.refresh(options.date.value)
  }

  function restartTimer(): void {
    clearTimer()
    if (!shouldPoll()) return
    timer = setInterval(pollOnce, options.intervalSeconds.value * 1000)
  }

  watch(
    [options.intervalSeconds, options.date, options.active],
    () => {
      restartTimer()
    },
    { immediate: true },
  )

  function onVisibilityChange(): void {
    if (
      typeof document !== "undefined" &&
      document.visibilityState === "visible"
    ) {
      pollOnce()
    }
  }

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibilityChange)
  }

  onBeforeUnmount(() => {
    clearTimer()
    if (typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", onVisibilityChange)
    }
  })
}
