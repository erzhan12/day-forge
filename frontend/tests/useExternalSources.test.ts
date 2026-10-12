import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount, type VueWrapper } from "@vue/test-utils"
import { h, nextTick, ref } from "vue"
import { useExternalSources } from "../src/composables/useExternalSources"
import ExternalEventsPanel from "../src/components/ExternalEventsPanel.vue"
import type { IntegrationBootstrap } from "../src/composables/useEventImport"

const requestJson = vi.hoisted(() => vi.fn())
vi.mock("../src/composables/useHttp", () => ({ requestJson }))

const date = "2026-06-23"
let snapshotCounter = 0
function bootstrap(connected: Partial<IntegrationBootstrap["connected"]> = {}): IntegrationBootstrap {
  return {
    snapshot_id: String(++snapshotCounter), user_id: 7, date, time_zone: "UTC",
    connected: { apple: false, google: false, todoist: false, habitica: false, ...connected },
    travel_rules: [],
  }
}

let wrapper: VueWrapper | undefined
function mountSources(initial = bootstrap(), renderEvents = false) {
  const selectedDate = ref(date)
  const timeZone = ref("UTC")
  const userId = ref<number | null | undefined>(7)
  const snapshot = ref<IntegrationBootstrap | undefined>(initial)
  let sources!: ReturnType<typeof useExternalSources>
  wrapper = mount({
    setup() {
      sources = useExternalSources({
        date: selectedDate, timeZone, todayDate: ref(date), userId,
        bootstrap: snapshot, isWide: ref(true), sidebarOpen: ref(true),
        placement: ref("center"), pollIntervalSeconds: ref(0),
      })
      return () => renderEvents ? h(ExternalEventsPanel, {
        events: sources.mergedExternalEvents.value,
        loading: sources.externalLoading.value,
        connected: sources.externalConnected.value,
        errorBanners: sources.externalErrorBanners.value,
        accountErrors: sources.googleCalendar.state.accountErrors,
        date: selectedDate.value,
        timeZone: timeZone.value,
      }) : null
    },
  })
  return { sources, selectedDate, timeZone, userId, snapshot }
}

async function settle() {
  await Promise.resolve()
  await nextTick()
  await Promise.resolve()
  await nextTick()
}

describe("useExternalSources", () => {
  beforeEach(() => {
    requestJson.mockReset()
    requestJson.mockImplementation(async (url: string) => {
      if (url.includes("/events/")) return { ok: true, data: { events: [], account_errors: [] } }
      if (url.includes("/tasks/")) return { ok: true, data: { tasks: [] } }
      return { ok: true, data: { connected: false, accounts: [] } }
    })
  })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined })

  it("starts no account or list requests for a disconnected bootstrap", async () => {
    mountSources()
    await settle()
    expect(requestJson).not.toHaveBeenCalled()
  })

  it("loads exactly the connected sources without account-status requests", async () => {
    mountSources(bootstrap({ apple: true, google: true, todoist: true, habitica: true }))
    await settle()
    const urls = requestJson.mock.calls.map(([url]) => url)
    expect(urls).toHaveLength(4)
    expect(urls).toContain(`/api/calendar/events/${date}/`)
    expect(urls).toContain(`/api/calendar/google/events/${date}/`)
    expect(urls).toContain(`/api/todoist/tasks/${date}/`)
    expect(urls).toContain(`/api/habitica/tasks/${date}/`)
    expect(urls.every((url: string) => !url.includes("account"))).toBe(true)
  })

  it("does not reapply stale bootstrap on a partial date reload", async () => {
    const { sources, selectedDate, snapshot } = mountSources(bootstrap({ apple: true }))
    await settle()
    sources.calendar.invalidateAccount("disconnected")
    snapshot.value = { ...snapshot.value! }
    await settle()
    expect(sources.calendar.state.connected).toBe(false)
    selectedDate.value = "2026-06-24"
    await settle()
    expect(sources.calendar.state.connected).toBe(false)
    expect(requestJson).toHaveBeenCalledTimes(1)
  })

  it("loads a source connected in Settings on a fresh same-date visit", async () => {
    const { sources, snapshot } = mountSources()
    await settle()
    snapshot.value = bootstrap({ todoist: true })
    await settle()
    expect(sources.todoist.state.connected).toBe(true)
    expect(requestJson.mock.calls.map(([url]) => url)).toEqual([`/api/todoist/tasks/${date}/`])
  })

  it("falls back to account status for a mismatched bootstrap before loading lists", async () => {
    requestJson.mockImplementation(async (url: string) => {
      if (url === "/api/calendar/account/") return { ok: true, data: { connected: true } }
      if (url.includes("/events/")) return { ok: true, data: { events: [] } }
      return { ok: true, data: { connected: false, accounts: [] } }
    })
    mountSources({ ...bootstrap(), date: "2026-06-22" })
    await settle()
    const urls = requestJson.mock.calls.map(([url]) => url)
    expect(urls.filter((url: string) => url.includes("/account"))).toHaveLength(4)
    expect(urls.filter((url: string) => url.includes("/events/"))).toEqual([`/api/calendar/events/${date}/`])
    expect(urls.filter((url: string) => url.includes("/tasks/"))).toEqual([])
  })

  it("accepts a fresh Settings return and rejects an in-flight response after disconnect", async () => {
    let resolveApple!: (result: object) => void
    requestJson.mockImplementation((url: string) => {
      if (url.includes("/api/calendar/events/")) {
        return new Promise((resolve) => { resolveApple = resolve })
      }
      return Promise.resolve({ ok: true, data: { events: [], tasks: [] } })
    })
    const { sources, snapshot } = mountSources(bootstrap({ apple: true }))
    await settle()
    snapshot.value = bootstrap()
    await settle()
    resolveApple({ ok: true, data: { events: [{ external_uid: "old" }] } })
    await settle()
    expect(sources.calendar.state.connected).toBe(false)
    expect(sources.calendar.state.events).toEqual([])
    expect(requestJson).toHaveBeenCalledTimes(1)
  })

  it("clears old rows and sends no requests when the authenticated user becomes null", async () => {
    const { sources, userId, snapshot } = mountSources(bootstrap({ apple: true }))
    await settle()
    sources.calendar.state.events = [{
      title: "Old", start: "2026-06-23T09:00:00Z", end: "2026-06-23T10:00:00Z",
      calendar_name: "Work", all_day: false, external_uid: "old", account_label: "",
    }]
    userId.value = null
    snapshot.value = { ...snapshot.value! }
    await settle()
    expect(sources.calendar.state.connected).toBe(false)
    expect(sources.calendar.state.events).toEqual([])
    expect(requestJson).toHaveBeenCalledTimes(1)
  })

  it("clears old rows when the user identity disappears", async () => {
    const { sources, userId } = mountSources(bootstrap({ todoist: true }))
    await settle()
    userId.value = undefined
    await settle()
    expect(sources.todoist.state.connected).toBe(false)
    expect(requestJson).toHaveBeenCalledTimes(1)
  })

  it("shows a Google all-account failure beside retained events in the panel, then clears on account switch", async () => {
    let googleReads = 0
    requestJson.mockImplementation(async (url: string) => {
      if (url.includes("/calendar/google/events/")) {
        googleReads += 1
        return googleReads === 1
          ? { ok: true, status: 200, data: {
            events: [{ title: "Team meeting", start: "2026-06-23T10:00:00Z", end: "2026-06-23T11:00:00Z", calendar_name: "Team", all_day: false, external_uid: "google-1", account_label: "alice@gmail.com" }],
            account_errors: [], meta: { account_state: "connected", resource_state: "ready" },
          } }
          : { ok: true, status: 200, data: {
            events: [], account_errors: [{ account_id: 1, email: "alice@gmail.com", error: "unavailable" }],
            meta: { account_state: "connected", resource_state: "provider_error" },
          } }
      }
      return { ok: true, data: { events: [], account_errors: [] } }
    })
    const { sources, snapshot } = mountSources(bootstrap({ google: true }), true)
    await settle()
    expect(wrapper!.find('[data-testid="external-event"]').text()).toContain("Team meeting")
    sources.refreshExternalCalendars()
    await settle()
    expect(wrapper!.find('[data-testid="provider-error"]').text()).toContain("Google Calendar service unavailable")
    expect(wrapper!.find('[data-testid="account-error"]').text()).toContain("alice@gmail.com")
    expect(wrapper!.find('[data-testid="external-event"]').text()).toContain("Team meeting")
    expect(wrapper!.find(".ee-empty").exists()).toBe(false)

    snapshot.value = bootstrap()
    await settle()
    expect(sources.googleCalendar.state.events).toEqual([])
    expect(sources.googleCalendar.state.accountErrors).toEqual([])
    expect(wrapper!.find('[data-testid="external-event"]').exists()).toBe(false)
  })

  it("shows a first Google all-account failure without an empty-day message", async () => {
    requestJson.mockImplementation(async (url: string) => url.includes("/calendar/google/events/")
      ? { ok: true, status: 200, data: {
        events: [], account_errors: [{ account_id: 1, email: "alice@gmail.com", error: "reconnect_required" }],
        meta: { account_state: "connected", resource_state: "credentials_error" },
      } }
      : { ok: true, data: { events: [], account_errors: [] } })
    mountSources(bootstrap({ google: true }), true)
    await settle()
    expect(wrapper!.find('[data-testid="provider-error"]').text()).toContain("authorization expired")
    expect(wrapper!.find('[data-testid="account-error"]').text()).toContain("needs reconnecting")
    expect(wrapper!.find('[data-testid="external-event"]').exists()).toBe(false)
    expect(wrapper!.find(".ee-empty").exists()).toBe(false)
  })
})
