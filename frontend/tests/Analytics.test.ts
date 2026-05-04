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

  it("cancels pending notes auto-save when the page unmounts", async () => {
    vi.useFakeTimers()
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

    // Type into the notes textarea and trigger the input handler so the
    // debounce timer is armed.
    const textarea = wrapper.find(".notes-input")
    await textarea.setValue("half-typed note")
    await textarea.trigger("input")

    // Unmount BEFORE the 1s debounce window elapses.
    wrapper.unmount()

    // Now advance past the debounce window. If the unmount cleanup
    // works, the PATCH must NOT fire.
    vi.advanceTimersByTime(2000)

    expect(fetchSpy).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
