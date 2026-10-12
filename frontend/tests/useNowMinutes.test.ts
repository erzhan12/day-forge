import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, nextTick, ref } from "vue"
import type { Ref } from "vue"
import { mount, type VueWrapper } from "@vue/test-utils"
import { useNowMinutes } from "../src/composables/useNowMinutes"

function mountHarness(initialDate: string, initialZone = "UTC"): {
  wrapper: VueWrapper
  date: Ref<string>
  zone: Ref<string>
  state: ReturnType<typeof useNowMinutes>
} {
  const date = ref(initialDate)
  const zone = ref(initialZone)
  let state!: ReturnType<typeof useNowMinutes>
  const Harness = defineComponent({
    setup() {
      state = useNowMinutes(date, zone)
      return {}
    },
    template: "<div />",
  })
  return { wrapper: mount(Harness), date, zone, state }
}

describe("useNowMinutes", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("uses one instant in the saved zone, independent of the browser zone", () => {
    vi.setSystemTime(new Date("2026-05-02T22:34:00Z"))
    const { wrapper, state } = mountHarness("2026-05-03", "Asia/Qatar")
    expect(state.todayDate.value).toBe("2026-05-03")
    expect(state.nowDate.value).toBe("2026-05-03")
    expect(state.nowMinutes.value).toBe(94)
    expect(state.currentHHMM.value).toBe("01:34")
    wrapper.unmount()
  })

  it("refreshes immediately when navigating into today and when the saved zone changes", async () => {
    vi.setSystemTime(new Date("2026-05-02T22:34:00Z"))
    const { wrapper, date, zone, state } = mountHarness("2026-05-02", "Asia/Qatar")
    expect(state.nowMinutes.value).toBeNull()
    date.value = "2026-05-03"
    await nextTick()
    expect(state.nowMinutes.value).toBe(94)
    zone.value = "UTC"
    await nextTick()
    expect(state.todayDate.value).toBe("2026-05-02")
    expect(state.nowMinutes.value).toBeNull()
    wrapper.unmount()
  })

  it("keeps one timer while off-today, so a future date enters today at midnight", async () => {
    vi.setSystemTime(new Date("2026-05-02T23:59:30Z"))
    const { wrapper, state } = mountHarness("2026-05-03")
    expect(state.nowMinutes.value).toBeNull()
    expect(vi.getTimerCount()).toBe(1)
    vi.advanceTimersByTime(60_000)
    await nextTick()
    expect(state.todayDate.value).toBe("2026-05-03")
    expect(state.nowDate.value).toBe("2026-05-03")
    expect(state.nowMinutes.value).toBe(0)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("leaves yesterday when midnight passes and keeps the timer for later navigation", async () => {
    vi.setSystemTime(new Date("2026-05-02T23:59:30Z"))
    const { wrapper, date, state } = mountHarness("2026-05-02")
    expect(state.nowMinutes.value).toBe(1439)
    vi.advanceTimersByTime(60_000)
    await nextTick()
    expect(state.nowMinutes.value).toBeNull()
    expect(state.todayDate.value).toBe("2026-05-03")
    date.value = "2026-05-03"
    await nextTick()
    expect(state.nowMinutes.value).toBe(0)
    expect(vi.getTimerCount()).toBe(1)
    wrapper.unmount()
  })

  it("resamples when a hidden tab becomes visible after midnight", async () => {
    vi.setSystemTime(new Date("2026-05-02T23:59:30Z"))
    const { wrapper, state } = mountHarness("2026-05-03")
    vi.setSystemTime(new Date("2026-05-03T00:05:00Z"))
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" })
    document.dispatchEvent(new Event("visibilitychange"))
    await nextTick()
    expect(state.nowDate.value).toBe("2026-05-03")
    expect(state.nowMinutes.value).toBe(5)
    wrapper.unmount()
  })
})
