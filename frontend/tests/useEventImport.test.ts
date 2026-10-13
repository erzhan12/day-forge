import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount, type VueWrapper } from "@vue/test-utils"
import { nextTick, ref } from "vue"
import { useEventImport, type IntegrationBootstrap } from "../src/composables/useEventImport"
import type { NormalizedEvent } from "../src/types/calendar"

const requestJson = vi.hoisted(() => vi.fn())
vi.mock("../src/composables/useHttp", () => ({ requestJson }))

const event: NormalizedEvent = {
  title: "Office", start: "2026-06-23T09:00:00Z", end: "2026-06-23T10:00:00Z",
  calendar_name: "Work", all_day: false, external_uid: "event-1", account_label: "",
}
const rule = {
  id: 1, keyword: "Office", calendar_name: "", travel_there_minutes: 20,
  travel_back_minutes: 15, category: "work", order: 1,
}
const snapshot: IntegrationBootstrap = {
  snapshot_id: "first", user_id: 7, date: "2026-06-23", time_zone: "UTC",
  connected: { apple: false, google: false, todoist: false, habitica: false },
  travel_rules: [rule],
}
let wrapper: VueWrapper | undefined
function mountImport(initial: IntegrationBootstrap | undefined = snapshot) {
  const date = ref("2026-06-23")
  const timeZone = ref("UTC")
  const userId = ref<number | null | undefined>(7)
  const bootstrap = ref(initial)
  let controller!: ReturnType<typeof useEventImport>
  wrapper = mount({
    setup() {
      controller = useEventImport({ date, timeZone, userId, bootstrap })
      return () => null
    },
  })
  return { controller, date, timeZone, userId, bootstrap }
}

describe("useEventImport", () => {
  beforeEach(() => { requestJson.mockReset() })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined })

  it("uses bootstrapped rules without an initial GET", async () => {
    const { controller } = mountImport()
    await controller.handleAddToSchedule(event)
    expect(controller.addDialogEvent.value).toEqual(event)
    expect(controller.addDialogRule.value).toEqual(rule)
    expect(requestJson).not.toHaveBeenCalled()
  })

  it("closes the dialog on date navigation and ignores a stale click after a slow rule read", async () => {
    let resolveLatest!: (result: object) => void
    requestJson.mockImplementation((_url: string, _method: string, _body: unknown, options?: { signal?: AbortSignal }) =>
      new Promise((resolve, reject) => {
        resolveLatest = resolve
        options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
      }),
    )
    const { controller, date } = mountImport({ ...snapshot, date: "2026-06-22" })
    const click = controller.handleAddToSchedule(event)
    date.value = "2026-06-24"
    await nextTick()
    resolveLatest({ ok: true, rules: [rule] })
    await click
    expect(controller.addDialogEvent.value).toBeNull()
    expect(requestJson).toHaveBeenCalledTimes(2)
  })

  it("aborts a pending rule read when the page unmounts", () => {
    let signal: AbortSignal | undefined
    requestJson.mockImplementation((_url: string, _method: string, _body: unknown, options?: { signal?: AbortSignal }) => {
      signal = options?.signal
      return new Promise(() => {})
    })
    mountImport({ ...snapshot, date: "2026-06-22" })
    expect(signal?.aborted).toBe(false)
    wrapper?.unmount()
    wrapper = undefined
    expect(signal?.aborted).toBe(true)
  })

  it("updates rules on a fresh bootstrap after Settings", async () => {
    const { controller, bootstrap } = mountImport()
    bootstrap.value = { ...snapshot, snapshot_id: "second", travel_rules: [] }
    await nextTick()
    await controller.handleAddToSchedule(event)
    expect(controller.addDialogRule.value).toBeNull()
  })

  it("closes an import dialog and does not fetch rules after logout", async () => {
    const { controller, userId, bootstrap } = mountImport()
    await controller.handleAddToSchedule(event)
    userId.value = null
    bootstrap.value = { ...snapshot }
    await nextTick()
    await controller.handleAddToSchedule(event)
    expect(controller.addDialogEvent.value).toBeNull()
    expect(requestJson).not.toHaveBeenCalled()
  })
})
