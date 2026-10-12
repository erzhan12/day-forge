import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { makeCategories } from "./helpers/schedule"

enableAutoUnmount(afterEach)

vi.mock("@inertiajs/vue3", () => ({
  Link: { template: "<a><slot /></a>" },
  router: { reload: vi.fn() },
  usePage: () => ({ props: {} }),
}))

import Analytics from "../src/pages/Analytics.vue"
import { router } from "@inertiajs/vue3"
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
    snapshot_kind: "current",
    reviewed_revision: null,
    ...overrides,
  }
}

function makeSchedule(status: Schedule["status"]): Schedule {
  return { id: 10, date: "2026-04-01", status, revision: 0 }
}

const STREAK: StreakInfo = { current: 3, threshold: 0.8, window_days: 30 }
const BLOCKS: TimeBlock[] = []

function mountAnalytics(overrides: Partial<InstanceType<typeof Analytics>["$props"]> = {}) {
  return mount(Analytics, {
    props: {
      review: makeReview(),
      streak: STREAK,
      schedule: makeSchedule("active"),
      blocks: BLOCKS,
      date: "2026-04-01",
      categories: makeCategories(),
      schedule_window: { start: "06:00", end: "23:00", time_zone: "Asia/Almaty" },
      ...overrides,
    },
  })
}

describe("Analytics.vue", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    document.cookie = "XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT"
  })

  it("renders all four panels", () => {
    const wrapper = mountAnalytics()
    expect(wrapper.findComponent({ name: "CompletionBar" }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: "CategoryBreakdown" }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: "StreakCounter" }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: "SkippedTasks" }).exists()).toBe(true)
  })

  it("shows a reload error for a malformed category catalog", () => {
    const malformed = makeCategories().map((category) => ({ ...category, is_sink: false }))
    const wrapper = mountAnalytics({ categories: malformed })
    expect(wrapper.get('[role="alert"]').text()).toContain("Category data could not be loaded")
    expect(wrapper.findComponent({ name: "CategoryBreakdown" }).exists()).toBe(false)
  })

  it("passes the persisted schedule timezone to the page-level mismatch prompt", () => {
    const wrapper = mountAnalytics()
    expect(wrapper.findComponent({ name: "TimeZoneMismatchPrompt" }).props("timeZone")).toBe("Asia/Almaty")
  })

  it("shows the Mark reviewed button when status is active", () => {
    const wrapper = mountAnalytics()
    expect(wrapper.find(".mark-reviewed-btn").exists()).toBe(true)
    expect(wrapper.text()).toContain("Active")
  })

  it("hides the Mark reviewed button when status is reviewed", () => {
    const wrapper = mountAnalytics({
      schedule: makeSchedule("reviewed"),
      review: makeReview({ status: "reviewed", snapshot_kind: "frozen", reviewed_revision: 0 }),
    })
    expect(wrapper.find(".mark-reviewed-btn").exists()).toBe(false)
    expect(wrapper.text()).toContain("Reviewed")
    expect(wrapper.find(".summary-label").text()).toBe("Reviewed summary")
  })

  it.each([null, 1])("offers explicit repair of a reviewed summary with tag %s", async (tag) => {
    document.cookie = "XSRF-TOKEN=test-token"
    const schedule = { ...makeSchedule("reviewed"), revision: 2 }
    const review = makeReview({ status: "reviewed", snapshot_kind: "current", reviewed_revision: tag })
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify({ schedule, blocks: [], revision: 2 })),
    })
    vi.stubGlobal("fetch", fetchSpy)
    const reloadSpy = vi.spyOn(router, "reload").mockImplementation((options) => {
      options?.onSuccess?.({} as never)
      options?.onFinish?.({} as never)
    })
    const wrapper = mountAnalytics({ schedule, review })

    expect(wrapper.get(".summary-label").text()).toBe("Current progress")
    expect(wrapper.get(".mark-reviewed-btn").text()).toBe("Update reviewed summary")
    await wrapper.get(".mark-reviewed-btn").trigger("click")
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(fetchSpy).toHaveBeenCalledOnce()
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/analytics/schedules/2026-04-01/mark-reviewed/")
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({ expected_revision: 2 })
    expect(reloadSpy).toHaveBeenCalled()
    await wrapper.setProps({ review: { ...review, snapshot_kind: "frozen", reviewed_revision: 2 } })
    expect(wrapper.find(".mark-reviewed-btn").exists()).toBe(false)
    expect(wrapper.get(".summary-label").text()).toBe("Reviewed summary")
  })

  it("does not hide review repair behind a frozen prop from an older revision", () => {
    const wrapper = mountAnalytics({
      schedule: { ...makeSchedule("reviewed"), revision: 2 },
      review: makeReview({ status: "reviewed", snapshot_kind: "frozen", reviewed_revision: 1 }),
    })
    expect(wrapper.get(".mark-reviewed-btn").text()).toBe("Update reviewed summary")
    expect(wrapper.get(".summary-label").text()).toBe("Summary needs update")
  })

  it("uses the canonical active status when an older frozen review prop remains", () => {
    const wrapper = mountAnalytics({
      schedule: { ...makeSchedule("active"), revision: 2 },
      review: makeReview({ status: "reviewed", snapshot_kind: "frozen", reviewed_revision: 1 }),
    })
    expect(wrapper.get(".mark-reviewed-btn").text()).toBe("Mark reviewed")
    expect(wrapper.get(".summary-label").text()).toBe("Summary needs update")
  })

  it("labels computed statistics as current progress even when a notes row exists", () => {
    const wrapper = mountAnalytics({ review: makeReview({ id: 19, snapshot_kind: "current" }) })
    expect(wrapper.find(".summary-label").text()).toBe("Current progress")
  })

  it.each(["draft", "active", "reviewed"] as const)(
    "keeps Daily export available for a %s schedule, including empty blocks",
    (status) => {
      const wrapper = mountAnalytics({
        schedule: makeSchedule(status),
        blocks: [],
        review: makeReview(status === "reviewed" ? { status, snapshot_kind: "frozen", reviewed_revision: 0 } : {}),
      })
      expect(wrapper.find(".daily-export-btn").exists()).toBe(true)
      expect(wrapper.find(".mark-reviewed-btn").exists()).toBe(status !== "reviewed")
    },
  )

  it("opens the export dialog with the viewed date and exact blocks, then closes it", async () => {
    const blocks = [
      {
        id: 55,
        title: "Export me",
        start_time: "08:00",
        end_time: "09:00",
        category: "work",
        is_completed: false,
        sort_order: 0,
      },
    ]
    const wrapper = mountAnalytics({ blocks })
    await wrapper.find(".daily-export-btn").trigger("click")
    const dialog = wrapper.findComponent({ name: "DailyExportDialog" })
    expect(dialog.exists()).toBe(true)
    expect(dialog.props("date")).toBe("2026-04-01")
    expect(dialog.props("blocks")).toStrictEqual(blocks)
    await dialog.vm.$emit("close")
    expect(wrapper.findComponent({ name: "DailyExportDialog" }).exists()).toBe(false)
  })

  it("clicking Mark reviewed posts to the API", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(JSON.stringify({ id: 1 })),
    })
    vi.stubGlobal("fetch", fetchSpy)

    const wrapper = mountAnalytics()
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

    const wrapper = mountAnalytics({
      review: makeReview({ id: 99 }),
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
    expect(url).toBe("/api/analytics/schedules/2026-04-01/notes/")
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

    const wrapper = mountAnalytics({
      review: makeReview({ id: 42 }),
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
    await vi.advanceTimersByTimeAsync(1_000)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/analytics/schedules/2026-04-01/notes/")
    expect(options.method).toBe("PATCH")

    vi.useRealTimers()
  })

  it("flushes pending notes to their captured date when date props change", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, status: 200, text: () => Promise.resolve("{}") })
    vi.stubGlobal("fetch", fetchSpy)
    const wrapper = mountAnalytics({ review: makeReview({ id: 42 }) })
    await wrapper.find(".notes-input").setValue("Previous day note")
    await wrapper.setProps({ date: "2026-04-02", schedule: { ...makeSchedule("active"), date: "2026-04-02" }, review: makeReview({ id: 43, date: "2026-04-02", notes: "New day" }) })
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/analytics/schedules/2026-04-01/notes/")
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({ notes: "Previous day note" })
    expect((wrapper.find(".notes-input").element as HTMLTextAreaElement).value).toBe("New day")
    vi.advanceTimersByTime(2000)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it("drops unsaved notes when the account identity changes", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn()
    vi.stubGlobal("fetch", fetchSpy)
    const wrapper = mountAnalytics({ auth_user_id: 1 })
    await wrapper.find(".notes-input").setValue("Previous user note")
    await wrapper.setProps({ auth_user_id: 2, review: makeReview({ id: 43, notes: "New user" }) })
    vi.advanceTimersByTime(2000)
    expect(fetchSpy).not.toHaveBeenCalled()
    expect((wrapper.find(".notes-input").element as HTMLTextAreaElement).value).toBe("New user")
    vi.useRealTimers()
  })

  it("keeps a draft when a nullable review gets a row after autosave", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, status: 200, text: () => Promise.resolve("{}") })
    vi.stubGlobal("fetch", fetchSpy)
    const wrapper = mountAnalytics({ auth_user_id: 7, review: makeReview({ id: null, created_at: null, updated_at: null }) })
    await wrapper.find(".notes-input").setValue("A note")
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/analytics/schedules/2026-04-01/notes/")
    expect(fetchSpy.mock.calls[0][1].headers["X-Schedule-User"]).toBe("7")

    await wrapper.setProps({ review: makeReview({ id: 99, notes: "A note" }) })
    expect((wrapper.find(".notes-input").element as HTMLTextAreaElement).value).toBe("A note")
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it("preserves an edited empty note when marking reviewed", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, text: () => Promise.resolve("{}") })
      .mockResolvedValueOnce({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify({ id: 1 })) })
    vi.stubGlobal("fetch", fetchSpy)
    vi.mocked(router.reload).mockImplementation((options) => { options?.onSuccess?.({} as never); options?.onFinish?.({} as never) })
    const wrapper = mountAnalytics({ review: makeReview({ notes: "Existing note" }) })
    await wrapper.find(".notes-input").setValue("")
    await wrapper.find(".mark-reviewed-btn").trigger("click")
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({ notes: "" })
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body)).toEqual({ expected_revision: 0, notes: "" })
    vi.advanceTimersByTime(2000)
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it("does not mix drafts when navigating away and back to the same date", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, status: 200, text: () => Promise.resolve("{}") })
    vi.stubGlobal("fetch", fetchSpy)
    const wrapper = mountAnalytics({ auth_user_id: 7, review: makeReview({ id: null }) })
    await wrapper.find(".notes-input").setValue("Old A")
    await wrapper.setProps({ date: "2026-04-02", schedule: { ...makeSchedule("active"), date: "2026-04-02" }, review: makeReview({ id: null, date: "2026-04-02", notes: "B" }) })
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/analytics/schedules/2026-04-01/notes/")
    await wrapper.find(".notes-input").setValue("Edited B")
    await wrapper.setProps({ date: "2026-04-01", schedule: makeSchedule("active"), review: makeReview({ id: null, notes: "Fresh A" }) })
    expect(fetchSpy.mock.calls[1][0]).toBe("/api/analytics/schedules/2026-04-02/notes/")
    expect((wrapper.find(".notes-input").element as HTMLTextAreaElement).value).toBe("Fresh A")
    vi.advanceTimersByTime(2000)
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it("keeps an edited note visible when autosave fails", async () => {
    vi.useFakeTimers()
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400, text: () => Promise.resolve(JSON.stringify({ errors: { detail: "Could not save this note" } })) }))
    const wrapper = mountAnalytics({ review: makeReview({ id: null, notes: "Original" }) })
    await wrapper.find(".notes-input").setValue("Edited")
    await vi.advanceTimersByTimeAsync(1000)
    expect((wrapper.find(".notes-input").element as HTMLTextAreaElement).value).toBe("Edited")
    expect(wrapper.find(".error").text()).toBe("Could not save this note")
    vi.useRealTimers()
  })

  it("does not flush on unmount if notes were not edited", async () => {
    vi.useFakeTimers()
    const fetchSpy = vi.fn()
    vi.stubGlobal("fetch", fetchSpy)

    const wrapper = mountAnalytics({
      review: makeReview({ notes: "saved" }),
    })

    // No keystroke → no armed timer → no flush.
    wrapper.unmount()
    vi.advanceTimersByTime(2000)
    expect(fetchSpy).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
