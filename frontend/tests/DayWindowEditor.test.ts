import { describe, it, expect, vi, beforeEach } from "vitest"
import { nextTick } from "vue"
import { mount, flushPromises } from "@vue/test-utils"
import type { ApiResult } from "../src/composables/useHttp"

// -- mocks ---------------------------------------------------------------
// vi.mock is hoisted; declare the shared spies via vi.hoisted so the
// factories can reference them.
const mocks = vi.hoisted(() => ({
  routerReloadSpy: vi.fn(),
  requestJsonSpy: vi.fn(),
}))

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: mocks.routerReloadSpy },
}))

vi.mock("../src/composables/useHttp", () => ({
  requestJson: mocks.requestJsonSpy,
}))

const { routerReloadSpy, requestJsonSpy } = mocks

import DayWindowEditor from "../src/components/DayWindowEditor.vue"

function mountEditor(window = { start: "06:00", end: "22:00", time_zone: "UTC" }) {
  return mount(DayWindowEditor, { props: { window } })
}

beforeEach(() => {
  routerReloadSpy.mockReset()
  requestJsonSpy.mockReset()
})

describe("DayWindowEditor", () => {
  it("seeds both HH:MM inputs from the schedule_window prop", () => {
    const wrapper = mountEditor({ start: "07:30", end: "21:45", time_zone: "Asia/Almaty" })
    const inputs = wrapper.findAll('input[type="time"]')
    expect(inputs).toHaveLength(2)
    expect((inputs[0].element as HTMLInputElement).value).toBe("07:30")
    expect((inputs[1].element as HTMLInputElement).value).toBe("21:45")
    expect((wrapper.find("select").element as HTMLSelectElement).value).toBe("Asia/Almaty")
  })

  it("re-seeds inputs when the window prop changes (deep watcher)", async () => {
    const wrapper = mountEditor({ start: "06:00", end: "22:00", time_zone: "UTC" })
    await wrapper.setProps({ window: { start: "08:00", end: "20:00", time_zone: "Europe/Berlin" } })
    const inputs = wrapper.findAll('input[type="time"]')
    expect((inputs[0].element as HTMLInputElement).value).toBe("08:00")
    expect((inputs[1].element as HTMLInputElement).value).toBe("20:00")
    expect((wrapper.find("select").element as HTMLSelectElement).value).toBe("Europe/Berlin")
  })

  // -- client-side validation (fast feedback, no PATCH) ------------------

  it("rejects a non-HH:MM start value and does NOT fire a PATCH", async () => {
    const wrapper = mountEditor()
    // A `type=time` input still accepts programmatic garbage via setValue.
    await wrapper.findAll('input[type="time"]')[0].setValue("9am")
    await wrapper.find("button").trigger("click")
    await flushPromises()
    expect(requestJsonSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("Use HH:MM format.")
  })

  it("rejects a start not on the 5-minute grid", async () => {
    const wrapper = mountEditor()
    await wrapper.findAll('input[type="time"]')[0].setValue("06:03")
    await wrapper.find("button").trigger("click")
    await flushPromises()
    expect(requestJsonSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("Use 5-minute increments.")
  })

  it("rejects end before/equal to start (same-day start<end)", async () => {
    const wrapper = mountEditor()
    const inputs = wrapper.findAll('input[type="time"]')
    await inputs[0].setValue("22:00")
    await inputs[1].setValue("06:00")
    await wrapper.find("button").trigger("click")
    await flushPromises()
    expect(requestJsonSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("End must be after start.")
  })

  // -- PATCH success ----------------------------------------------------

  it("valid input → PATCHes schedule-settings and triggers router.reload", async () => {
    requestJsonSpy.mockResolvedValueOnce({ ok: true } as ApiResult)
    const wrapper = mountEditor({ start: "06:00", end: "22:00", time_zone: "UTC" })
    const inputs = wrapper.findAll('input[type="time"]')
    await inputs[0].setValue("07:00")
    await inputs[1].setValue("23:00")
    await wrapper.find("button").trigger("click")
    await flushPromises()
    expect(requestJsonSpy).toHaveBeenCalledWith(
      "/api/user/schedule-settings/",
      "PATCH",
      { day_start: "07:00", day_end: "23:00", time_zone: "UTC" },
    )
    expect(routerReloadSpy).toHaveBeenCalledWith({ only: ["schedule_window"] })
  })

  it("disables inputs and shows 'Saving…' while the PATCH is in flight", async () => {
    let resolveSave: ((r: ApiResult) => void) | undefined
    requestJsonSpy.mockImplementationOnce(
      () => new Promise<ApiResult>((r) => (resolveSave = r)),
    )
    const wrapper = mountEditor()
    await wrapper.find("button").trigger("click")
    await nextTick()
    const inputs = wrapper.findAll('input[type="time"]')
    expect((inputs[0].element as HTMLInputElement).disabled).toBe(true)
    expect((inputs[1].element as HTMLInputElement).disabled).toBe(true)
    expect((wrapper.find("select").element as HTMLSelectElement).disabled).toBe(true)
    expect(wrapper.find("button").text()).toBe("Saving…")
    resolveSave!({ ok: true })
    await flushPromises()
    expect(wrapper.find("button").text()).toBe("Save")
  })

  // -- PATCH error (400 structured field errors) ------------------------

  it("400 field errors → surfaces them AND reverts inputs to last saved prop", async () => {
    requestJsonSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      errors: { day_end: "End must be after start." },
    } as ApiResult)
    const wrapper = mountEditor({ start: "06:00", end: "22:00", time_zone: "UTC" })
    const inputs = wrapper.findAll('input[type="time"]')
    // Edit to a locally-valid pair that the server rejects.
    await inputs[0].setValue("07:00")
    await inputs[1].setValue("23:00")
    await wrapper.find("button").trigger("click")
    await flushPromises()

    expect(routerReloadSpy).not.toHaveBeenCalled()
    // Server error message is shown.
    expect(wrapper.text()).toContain("End must be after start.")
    // Preserve-on-failure: inputs revert to the last saved prop value.
    expect((inputs[0].element as HTMLInputElement).value).toBe("06:00")
    expect((inputs[1].element as HTMLInputElement).value).toBe("22:00")
  })

  it("array-valued field errors are joined into a single message", async () => {
    requestJsonSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      errors: { day_start: ["Use HH:MM format.", "Required."] },
    } as ApiResult)
    const wrapper = mountEditor()
    await wrapper.find("button").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("Use HH:MM format. Required.")
  })

  it("error result with no `errors` payload → falls back to a generic message", async () => {
    requestJsonSpy.mockResolvedValueOnce({ ok: false, status: 500 } as ApiResult)
    const wrapper = mountEditor({ start: "06:00", end: "22:00", time_zone: "UTC" })
    const inputs = wrapper.findAll('input[type="time"]')
    await inputs[1].setValue("23:00")
    await wrapper.find("button").trigger("click")
    await flushPromises()
    expect(routerReloadSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("Unable to save day window.")
    // Still reverts on failure.
    expect((inputs[1].element as HTMLInputElement).value).toBe("22:00")
  })

  it("shows a timezone field error and reverts the selector to its persisted prop", async () => {
    requestJsonSpy.mockResolvedValueOnce({
      ok: false,
      status: 400,
      errors: { time_zone: "Must be a valid IANA time zone." },
    } as ApiResult)
    const wrapper = mountEditor({ start: "06:00", end: "22:00", time_zone: "Asia/Almaty" })
    await wrapper.find("select").setValue("Europe/Berlin")
    await wrapper.find("button").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("Must be a valid IANA time zone.")
    expect((wrapper.find("select").element as HTMLSelectElement).value).toBe("Asia/Almaty")
    expect(routerReloadSpy).not.toHaveBeenCalled()
  })
})
