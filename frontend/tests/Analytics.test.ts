import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"

vi.mock("@inertiajs/vue3", () => ({
  Link: { template: "<a><slot /></a>" },
  router: { reload: vi.fn() },
}))

import Analytics from "../src/pages/Analytics.vue"
import type { DailyReview, Schedule, StreakInfo, TimeBlock } from "../src/types"

function makeReview(overrides: Partial<DailyReview> = {}): DailyReview {
  return {
    id: 1,
    schedule_id: 10,
    date: "2026-04-01",
    status: "active",
    planned_count: 4,
    completed_count: 2,
    skipped_count: 1,
    completion_rate: 0.5,
    planned_minutes_by_category: {
      work: 120, personal: 0, health: 60, other: 0,
    },
    completed_minutes_by_category: {
      work: 60, personal: 0, health: 30, other: 0,
    },
    notes: "",
    created_at: "2026-04-01T08:00:00",
    updated_at: "2026-04-01T08:00:00",
    ...overrides,
  }
}

function makeSchedule(status: Schedule["status"]): Schedule {
  return { id: 10, date: "2026-04-01", status }
}

const STREAK: StreakInfo = { current: 3, threshold: 0.8, window_days: 30 }
const BLOCKS: TimeBlock[] = []

describe("Analytics.vue", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    document.cookie = "XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT"
  })

  it("renders all four panels", () => {
    const wrapper = mount(Analytics, {
      props: {
        review: makeReview(),
        streak: STREAK,
        schedule: makeSchedule("active"),
        blocks: BLOCKS,
        date: "2026-04-01",
      },
    })
    expect(wrapper.findComponent({ name: "CompletionBar" }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: "CategoryBreakdown" }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: "StreakCounter" }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: "SkippedTasks" }).exists()).toBe(true)
  })

  it("shows the Mark reviewed button when status is active", () => {
    const wrapper = mount(Analytics, {
      props: {
        review: makeReview(),
        streak: STREAK,
        schedule: makeSchedule("active"),
        blocks: BLOCKS,
        date: "2026-04-01",
      },
    })
    expect(wrapper.find(".mark-reviewed-btn").exists()).toBe(true)
    expect(wrapper.text()).toContain("Active")
  })

  it("hides the Mark reviewed button when status is reviewed", () => {
    const wrapper = mount(Analytics, {
      props: {
        review: makeReview(),
        streak: STREAK,
        schedule: makeSchedule("reviewed"),
        blocks: BLOCKS,
        date: "2026-04-01",
      },
    })
    expect(wrapper.find(".mark-reviewed-btn").exists()).toBe(false)
    expect(wrapper.text()).toContain("Reviewed")
  })

  it("clicking Mark reviewed posts to the API", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify({ id: 1 })),
    })
    vi.stubGlobal("fetch", fetchSpy)

    const wrapper = mount(Analytics, {
      props: {
        review: makeReview(),
        streak: STREAK,
        schedule: makeSchedule("active"),
        blocks: BLOCKS,
        date: "2026-04-01",
      },
    })
    await wrapper.find(".mark-reviewed-btn").trigger("click")
    // Wait microtask queue
    await new Promise((r) => setTimeout(r, 0))
    expect(fetchSpy).toHaveBeenCalled()
    const [url] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/analytics/schedules/2026-04-01/mark-reviewed/")
  })

  it("flushes a pending notes auto-save when the page unmounts", async () => {
    // Regression: dropping the pending PATCH would lose a half-typed
    // note when the user navigates away < 1s after typing. Flush
    // instead. The debounce timer is cleared (so no double-fire after
    // unmount), but the PATCH IS issued synchronously from the
    // unmount handler.
    vi.useFakeTimers()
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify({ id: 1 })),
    })
    vi.stubGlobal("fetch", fetchSpy)

    const wrapper = mount(Analytics, {
      props: {
        review: makeReview({ id: 99 }),
        streak: STREAK,
        schedule: makeSchedule("active"),
        blocks: BLOCKS,
        date: "2026-04-01",
      },
    })

    const textarea = wrapper.find(".notes-input")
    await textarea.setValue("half-typed note")
    await textarea.trigger("input")

    // Unmount BEFORE the 1s debounce window elapses.
    wrapper.unmount()

    // The flush PATCH should fire synchronously from onUnmounted —
    // no need to advance timers. (Advancing them would be a no-op
    // anyway because the timer was cleared.)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/analytics/reviews/99/notes/")
    expect(options.method).toBe("PATCH")
    expect(JSON.parse(options.body)).toEqual({ notes: "half-typed note" })

    // Advancing past the debounce window must NOT trigger a second
    // PATCH (would mean the timer wasn't actually cleared).
    vi.advanceTimersByTime(2000)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it("debounces notes PATCH until 1s after the last input", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve("{}"),
    })
    vi.stubGlobal("fetch", fetchSpy)

    const wrapper = mount(Analytics, {
      props: {
        review: makeReview({ id: 42 }),
        streak: STREAK,
        schedule: makeSchedule("active"),
        blocks: BLOCKS,
        date: "2026-04-01",
      },
    })

    const textarea = wrapper.find(".notes-input")
    await textarea.setValue("a")
    await textarea.trigger("input")
    vi.advanceTimersByTime(500)
    expect(fetchSpy).not.toHaveBeenCalled()

    await textarea.setValue("ab")
    await textarea.trigger("input")
    // Intermediate checkpoint: at 500ms past the SECOND input, the first
    // input's timer would have fired (1000ms total) if it weren't cancelled.
    // No call here means the second input correctly resets the debounce.
    vi.advanceTimersByTime(500)
    expect(fetchSpy).not.toHaveBeenCalled()
    vi.advanceTimersByTime(499)
    expect(fetchSpy).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    await vi.runAllTimersAsync()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/analytics/reviews/42/notes/")
    expect(options.method).toBe("PATCH")

    vi.useRealTimers()
  })

  it("does not flush on unmount if notes were not edited", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn()
    vi.stubGlobal("fetch", fetchSpy)

    const wrapper = mount(Analytics, {
      props: {
        review: makeReview({ notes: "saved" }),
        streak: STREAK,
        schedule: makeSchedule("active"),
        blocks: BLOCKS,
        date: "2026-04-01",
      },
    })

    // No keystroke → no armed timer → no flush.
    wrapper.unmount()
    vi.advanceTimersByTime(2000)
    expect(fetchSpy).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
