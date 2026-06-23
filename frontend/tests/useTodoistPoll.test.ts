import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ref } from "vue"
import { useTodoistPoll } from "../src/composables/useTodoistPoll"

describe("useTodoistPoll", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    })
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it("does not poll when interval is 0", () => {
    const refresh = vi.fn()
    const intervalSeconds = ref(0)
    const date = ref("2026-06-23")
    const active = ref(true)

    useTodoistPoll({ intervalSeconds, date, active, refresh })

    vi.advanceTimersByTime(60_000)
    expect(refresh).not.toHaveBeenCalled()
  })

  it("polls on the configured interval while active", () => {
    const refresh = vi.fn()
    const intervalSeconds = ref(10)
    const date = ref("2026-06-23")
    const active = ref(true)

    useTodoistPoll({ intervalSeconds, date, active, refresh })

    vi.advanceTimersByTime(10_000)
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(refresh).toHaveBeenCalledWith("2026-06-23")

    vi.advanceTimersByTime(10_000)
    expect(refresh).toHaveBeenCalledTimes(2)
  })

  it("stops polling when active becomes false", () => {
    const refresh = vi.fn()
    const intervalSeconds = ref(10)
    const date = ref("2026-06-23")
    const active = ref(true)

    useTodoistPoll({ intervalSeconds, date, active, refresh })

    vi.advanceTimersByTime(10_000)
    expect(refresh).toHaveBeenCalledTimes(1)

    active.value = false
    vi.advanceTimersByTime(30_000)
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it("uses the current date after navigation", () => {
    const refresh = vi.fn()
    const intervalSeconds = ref(10)
    const date = ref("2026-06-23")
    const active = ref(true)

    useTodoistPoll({ intervalSeconds, date, active, refresh })

    date.value = "2026-06-24"
    vi.advanceTimersByTime(10_000)
    expect(refresh).toHaveBeenLastCalledWith("2026-06-24")
  })

  it("skips ticks while the document is hidden", () => {
    const refresh = vi.fn()
    const intervalSeconds = ref(10)
    const date = ref("2026-06-23")
    const active = ref(true)

    useTodoistPoll({ intervalSeconds, date, active, refresh })

    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    })
    vi.advanceTimersByTime(10_000)
    expect(refresh).not.toHaveBeenCalled()
  })

  it("refreshes once when the tab becomes visible again", () => {
    const refresh = vi.fn()
    const intervalSeconds = ref(10)
    const date = ref("2026-06-23")
    const active = ref(true)

    useTodoistPoll({ intervalSeconds, date, active, refresh })

    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    })
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    })
    vi.advanceTimersByTime(10_000)
    expect(refresh).not.toHaveBeenCalled()

    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    })
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    })
    document.dispatchEvent(new Event("visibilitychange"))
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(refresh).toHaveBeenCalledWith("2026-06-23")
  })
})
