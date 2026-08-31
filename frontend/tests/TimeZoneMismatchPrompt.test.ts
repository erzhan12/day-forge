import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

const mocks = vi.hoisted(() => ({ reload: vi.fn(), request: vi.fn() }))
let detectedZone = "Asia/Almaty"
vi.mock("@inertiajs/vue3", () => ({ router: { reload: mocks.reload } }))
vi.mock("../src/composables/useHttp", () => ({ requestJson: mocks.request }))

let TimeZoneMismatchPrompt: typeof import("../src/components/TimeZoneMismatchPrompt.vue").default

beforeEach(async () => {
  vi.resetModules()
  TimeZoneMismatchPrompt = (await import("../src/components/TimeZoneMismatchPrompt.vue")).default
  detectedZone = "Asia/Almaty"
  mocks.reload.mockReset()
  mocks.request.mockReset()
  localStorage.clear()
  vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => (
    { resolvedOptions: () => ({ timeZone: detectedZone }) } as Intl.DateTimeFormat
  ))
})

describe("TimeZoneMismatchPrompt", () => {
  it("only renders for a mismatch and does not update automatically", () => {
    expect(mount(TimeZoneMismatchPrompt, { props: { timeZone: "Asia/Almaty" } }).text()).toBe("")
    const wrapper = mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } })
    expect(wrapper.text()).toContain("Your timezone looks like Asia/Almaty — update your settings?")
    expect(mocks.request).not.toHaveBeenCalled()
  })

  it("dismisses the exact detected zone", async () => {
    const wrapper = mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } })
    await wrapper.get("button:last-of-type").trigger("click")
    expect(wrapper.text()).toBe("")
    expect(mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } }).text()).toBe("")
  })

  it("updates only timezone then reloads the route prop", async () => {
    detectedZone = "America/New_York"
    mocks.request.mockResolvedValue({ ok: true })
    const wrapper = mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } })
    await wrapper.get("button").trigger("click")
    await flushPromises()
    expect(mocks.request).toHaveBeenCalledWith(
      "/api/user/schedule-settings/", "PATCH", { time_zone: "America/New_York" },
    )
    expect(mocks.reload).toHaveBeenCalledWith({ only: ["schedule_window"] })
  })

  it("keeps a failed update visible, shows its error, and allows retry without marking handled", async () => {
    detectedZone = "Europe/Berlin"
    mocks.request.mockResolvedValueOnce({ ok: false, errors: { time_zone: "Try again." } })
    const wrapper = mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } })

    await wrapper.get("button").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("Try again.")
    expect(wrapper.text()).toContain("Your timezone looks like Europe/Berlin")
    expect(mocks.reload).not.toHaveBeenCalled()
    expect(mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } }).text()).toContain("Europe/Berlin")

    mocks.request.mockResolvedValueOnce({ ok: true })
    await wrapper.get("button").trigger("click")
    await flushPromises()
    expect(mocks.request).toHaveBeenCalledTimes(2)
    expect(mocks.reload).toHaveBeenCalledWith({ only: ["schedule_window"] })
  })

  it("prompts again when detection changes after a different zone was dismissed", async () => {
    detectedZone = "Pacific/Kiritimati"
    const first = mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } })
    await first.get("button:last-of-type").trigger("click")
    detectedZone = "Europe/Berlin"
    expect(mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } }).text()).toContain("Europe/Berlin")
  })

  it("does not break rendering when timezone detection or storage fails", () => {
    const dateTimeFormat = vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => { throw new Error("no intl") })
    expect(() => mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } })).not.toThrow()
    dateTimeFormat.mockRestore()
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => { throw new Error("storage blocked") }),
      setItem: vi.fn(() => { throw new Error("storage blocked") }),
    })
    expect(() => mount(TimeZoneMismatchPrompt, { props: { timeZone: "UTC" } })).not.toThrow()
  })
})
