import { describe, it, expect, vi, beforeEach } from "vitest"
import { effectScope, ref } from "vue"
import { computeEventBlockTimes } from "../src/utils/travelRules"
import { isExternalEventPast } from "../src/utils/externalEventPast"
import { useCalendar } from "../src/composables/useCalendar"
import { useGoogleCalendar } from "../src/composables/useGoogleCalendar"
import { useTodoist } from "../src/composables/useTodoist"
import { useHabitica } from "../src/composables/useHabitica"
import { requestJson } from "../src/composables/useHttp"

vi.mock("../src/composables/useHttp", () => ({ requestJson: vi.fn() }))
const event = {
  title: "Meeting", start: "2026-10-10T20:30:00Z", end: "2026-10-10T21:30:00Z",
  all_day: false, calendar_name: "Work", external_uid: "1", account_label: "",
}

describe("external event civil time", () => {
  it.each([
    ["UTC", "2026-10-10", "20:20", "21:45"],
    ["Asia/Qatar", "2026-10-10", "23:20", "23:59"],
    ["Asia/Qatar", "2026-10-11", "00:00", "00:45"],
    ["Asia/Kathmandu", "2026-10-11", "02:05", "03:30"],
    ["America/Los_Angeles", "2026-10-10", "13:20", "14:45"],
  ])("maps travel padding in %s onto %s", (zone, day, start, end) => {
    expect(computeEventBlockTimes(event, day, 10, 15, zone))
      .toEqual({ start_time: start, end_time: end })
  })

  it("uses all-day dates even when the serialized instant belongs to another day", () => {
    const allDay = { ...event, all_day: true, start_date: "2026-10-10", end_date: "2026-10-11" }
    expect(computeEventBlockTimes(allDay, "2026-10-10", 0, 0, "Asia/Kathmandu"))
      .toEqual({ start_time: "00:00", end_time: "23:59" })
    expect(computeEventBlockTimes(allDay, "2026-10-11", 0, 0, "Asia/Kathmandu")).toBeNull()
  })

  it("keeps a next-local-day end upcoming and compares it on its own day", () => {
    expect(isExternalEventPast(event, "2026-10-10", "2026-10-10", 1439, "Asia/Qatar")).toBe(false)
    expect(isExternalEventPast(event, "2026-10-11", "2026-10-11", 30, "Asia/Qatar")).toBe(true)
  })

  it("maps DST spring-forward by wall clock and preserves repeated-hour limitation", () => {
    expect(computeEventBlockTimes({ start: "2026-03-08T06:30:00Z", end: "2026-03-08T07:30:00Z" }, "2026-03-08", 0, 0, "America/New_York"))
      .toEqual({ start_time: "01:30", end_time: "03:30" })
    // Two distinct instants share 01:30. The naive block model cannot encode
    // this elapsed hour; the dialog's zero-duration guard requires adjustment.
    expect(computeEventBlockTimes({ start: "2026-11-01T05:30:00Z", end: "2026-11-01T06:30:00Z" }, "2026-11-01", 0, 0, "America/New_York"))
      .toEqual({ start_time: "01:30", end_time: "01:30" })
  })
})

describe("external source context changes", () => {
  beforeEach(() => vi.mocked(requestJson).mockReset())
  it.each([useTodoist, useHabitica])("does not restore a failed completion across an A-B-A timezone change", async (factory) => {
    const scope = effectScope()
    const context = ref("UTC:2026-10-10")
    const source = scope.run(() => factory(() => context.value))!
    vi.mocked(requestJson).mockResolvedValueOnce({ ok: true, data: { tasks: [{ id: "old" }] } })
    await source.fetchTasks("2026-10-10")
    let resolve!: (value: Awaited<ReturnType<typeof requestJson>>) => void
    vi.mocked(requestJson).mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const completion = source.completeTask("old")
    context.value = "Asia/Qatar:2026-10-10"
    context.value = "UTC:2026-10-10"
    vi.mocked(requestJson).mockResolvedValueOnce({ ok: true, data: { tasks: [{ id: "new" }] } })
    await source.fetchTasks("2026-10-10")
    resolve({ ok: false, status: 500 })
    await completion
    expect(source.state.tasks.map((task) => task.id)).toEqual(["new"])
    expect(source.state.error).toBeNull()
    scope.stop()
  })
  it.each([
    ["Apple", useCalendar, "fetchEvents", "events"],
    ["Google", useGoogleCalendar, "fetchEvents", "events"],
    ["Todoist", useTodoist, "fetchTasks", "tasks"],
    ["Habitica", useHabitica, "fetchTasks", "tasks"],
  ] as const)("%s clears cached rows and ignores a late response after timezone changes", async (_, factory, method, key) => {
    const scope = effectScope()
    const context = ref("UTC:2026-10-10")
    const source = scope.run(() => factory(() => context.value))!
    const load = (date: string) => method === "fetchEvents"
      ? (source as ReturnType<typeof useCalendar>).fetchEvents(date)
      : (source as ReturnType<typeof useTodoist>).fetchTasks(date)
    vi.mocked(requestJson).mockResolvedValueOnce({ ok: true, data: { [key]: [event] } })
    await load("2026-10-10")
    let resolve!: (value: Awaited<ReturnType<typeof requestJson>>) => void
    vi.mocked(requestJson).mockImplementationOnce(() => new Promise((r) => { resolve = r }))
    const pending = load("2026-10-10")
    const signal = vi.mocked(requestJson).mock.calls.at(-1)![3]?.signal
    context.value = "Asia/Qatar:2026-10-11"
    expect(signal?.aborted).toBe(true)
    resolve({ ok: true, data: { [key]: [event] } })
    await pending
    expect((source.state as unknown as Record<string, unknown>)[key]).toEqual([])
    scope.stop()
  })
})
