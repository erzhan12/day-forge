import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, nextTick, ref } from "vue"
import type { Ref } from "vue"
import { mount, type VueWrapper } from "@vue/test-utils"
import { todayString } from "../src/utils/date"
import { useNowMinutes } from "../src/composables/useNowMinutes"

function mountHarness(initialDate: string): {
  wrapper: VueWrapper
  date: Ref<string>
  state: ReturnType<typeof useNowMinutes>
} {
  const date = ref(initialDate)
  let state!: ReturnType<typeof useNowMinutes>
  const Harness = defineComponent({
    setup() {
      state = useNowMinutes(date)
      return {}
    },
    template: "<div />",
  })

  return { wrapper: mount(Harness), date, state }
}

describe("useNowMinutes", () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("refreshes immediately when navigating into today on the same instance", async () => {
    vi.setSystemTime(new Date(2026, 4, 3, 12, 34))
    const { wrapper, date, state } = mountHarness("2026-05-02")

    expect(state.nowMinutes.value).toBeNull()
    date.value = todayString()
    await nextTick()

    expect(state.nowMinutes.value).toBe(12 * 60 + 34)
    expect(state.nowDate.value).toBe("2026-05-03")
    expect(state.currentHHMM.value).toBe("12:34")
    wrapper.unmount()
  })

  it("ticks while viewing today", async () => {
    vi.setSystemTime(new Date(2026, 4, 3, 12, 0))
    const { wrapper, state } = mountHarness(todayString())

    expect(state.nowMinutes.value).toBe(12 * 60)
    vi.advanceTimersByTime(60_000)
    await nextTick()

    expect(state.nowMinutes.value).toBe(12 * 60 + 1)
    expect(state.currentHHMM.value).toBe("12:01")
    wrapper.unmount()
  })

  it("clears the interval and refs when leaving today", async () => {
    vi.setSystemTime(new Date(2026, 4, 3, 12, 0))
    const { wrapper, date, state } = mountHarness(todayString())
    expect(vi.getTimerCount()).toBe(1)

    date.value = "2026-05-02"
    await nextTick()

    expect(vi.getTimerCount()).toBe(0)
    expect(state.nowMinutes.value).toBeNull()
    expect(state.nowDate.value).toBeNull()
    expect(state.currentHHMM.value).toBe("")

    vi.setSystemTime(new Date(2026, 4, 3, 12, 1))
    vi.advanceTimersByTime(60_000)
    await nextTick()
    expect(state.nowMinutes.value).toBeNull()
    wrapper.unmount()
  })

  it("samples fresh time on a today to non-today to today round trip", async () => {
    vi.setSystemTime(new Date(2026, 4, 3, 9, 0))
    const { wrapper, date, state } = mountHarness(todayString())
    expect(state.nowMinutes.value).toBe(9 * 60)

    date.value = "2026-05-02"
    await nextTick()
    vi.setSystemTime(new Date(2026, 4, 3, 15, 45))
    date.value = todayString()
    await nextTick()

    expect(state.nowMinutes.value).toBe(15 * 60 + 45)
    expect(state.currentHHMM.value).toBe("15:45")
    wrapper.unmount()
  })

  it("does not leak duplicate intervals across repeated re-entry", async () => {
    vi.setSystemTime(new Date(2026, 4, 3, 9, 0))
    const setSpy = vi.spyOn(globalThis, "setInterval")
    const clearSpy = vi.spyOn(globalThis, "clearInterval")

    const { wrapper, date } = mountHarness(todayString())
    expect(vi.getTimerCount()).toBe(1)
    expect(setSpy).toHaveBeenCalledTimes(1)
    expect(clearSpy).not.toHaveBeenCalled()

    date.value = "2026-05-02"
    await nextTick()
    expect(vi.getTimerCount()).toBe(0)
    expect(clearSpy).toHaveBeenCalledTimes(1)

    date.value = todayString()
    await nextTick()
    expect(vi.getTimerCount()).toBe(1)
    expect(setSpy).toHaveBeenCalledTimes(2)

    date.value = "2026-05-02"
    await nextTick()
    date.value = todayString()
    await nextTick()
    expect(vi.getTimerCount()).toBe(1)
    expect(setSpy).toHaveBeenCalledTimes(3)
    expect(clearSpy).toHaveBeenCalledTimes(2)

    // Every new handle must be preceded by a clear of the prior one
    // — replace-without-clear would still satisfy getTimerCount() === 1.
    const sets = setSpy.mock.invocationCallOrder
    const clears = clearSpy.mock.invocationCallOrder
    expect(clears[0]).toBeLessThan(sets[1])
    expect(clears[1]).toBeLessThan(sets[2])

    wrapper.unmount()
    setSpy.mockRestore()
    clearSpy.mockRestore()
  })

  it("leaves today when the wall clock rolls past midnight without navigation", async () => {
    vi.setSystemTime(new Date(2026, 4, 22, 23, 59, 50))
    const setSpy = vi.spyOn(globalThis, "setInterval")
    const { wrapper, state } = mountHarness("2026-05-22")

    expect(state.nowDate.value).toBe("2026-05-22")
    expect(vi.getTimerCount()).toBe(1)
    expect(setSpy).toHaveBeenCalledTimes(1)

    vi.setSystemTime(new Date(2026, 4, 23, 0, 0, 10))
    vi.advanceTimersByTime(60_000)
    await nextTick()

    expect(state.nowMinutes.value).toBeNull()
    expect(state.nowDate.value).toBeNull()
    expect(state.currentHHMM.value).toBe("")
    expect(vi.getTimerCount()).toBe(0)
    // Rollover branch must not arm a fresh interval.
    expect(setSpy).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(60_000)
    await nextTick()
    expect(state.nowMinutes.value).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
    expect(setSpy).toHaveBeenCalledTimes(1)
    wrapper.unmount()
    setSpy.mockRestore()
  })

  it("cleans up the interval on unmount", () => {
    vi.setSystemTime(new Date(2026, 4, 3, 12, 0))
    const { wrapper } = mountHarness(todayString())
    expect(vi.getTimerCount()).toBe(1)

    wrapper.unmount()

    expect(vi.getTimerCount()).toBe(0)
  })
})
