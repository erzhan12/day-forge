import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"
import type { TimeBlock } from "../src/types"

const mockCreateBlock = vi.fn()
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    createBlock: mockCreateBlock,
  }),
}))

import AddBlockForm from "../src/components/AddBlockForm.vue"

const mockPushUndo = vi.fn()
const mockSnapshotBlocks = vi.fn(() => [])

function mountForm(props: { date: string; initialStartTime?: string; initialEndTime?: string }) {
  return mount(AddBlockForm, {
    props,
    global: {
      provide: {
        undo: { pushUndo: mockPushUndo, snapshotBlocks: mockSnapshotBlocks },
      },
    },
  })
}

describe("AddBlockForm", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("shows add button initially, not the form", () => {
    const wrapper = mountForm({ date: "2026-04-10" })
    expect(wrapper.find(".add-btn").exists()).toBe(true)
    expect(wrapper.find(".add-form").exists()).toBe(false)
  })

  it("shows form when add button clicked", async () => {
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    expect(wrapper.find(".add-form").exists()).toBe(true)
    expect(wrapper.find(".add-btn").exists()).toBe(false)
  })

  it("hides form on cancel", async () => {
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".cancel-btn").trigger("click")
    expect(wrapper.find(".add-form").exists()).toBe(false)
  })

  it("does not submit with empty title", async () => {
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find("form").trigger("submit")
    expect(mockCreateBlock).not.toHaveBeenCalled()
  })

  it("submits with valid data and resets form", async () => {
    mockCreateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".title-input").setValue("New Block")
    await wrapper.find("form").trigger("submit")
    await vi.dynamicImportSettled()

    expect(mockCreateBlock).toHaveBeenCalledWith({
      title: "New Block",
      start_time: "09:00",
      end_time: "10:00",
      category: "work",
    })
    // Form should hide on success
    expect(wrapper.find(".add-form").exists()).toBe(false)
  })

  it("shows error on failed submission", async () => {
    mockCreateBlock.mockResolvedValue({
      ok: false,
      errors: { time: "This block overlaps with an existing block." },
    })
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".title-input").setValue("Overlap")
    await wrapper.find("form").trigger("submit")
    await vi.dynamicImportSettled()

    expect(wrapper.find(".error-banner").exists()).toBe(true)
    expect(wrapper.text()).toContain("overlaps")
    // Form should remain visible
    expect(wrapper.find(".add-form").exists()).toBe(true)
  })

  it("uses initial start/end times from props", async () => {
    const wrapper = mountForm({ date: "2026-04-10", initialStartTime: "14:00", initialEndTime: "15:00" })
    // With initial times provided, form doesn't auto-show (only when they change)
    await wrapper.find(".add-btn").trigger("click")
    const startInput = wrapper.find('input[type="time"]')
    expect((startInput.element as HTMLInputElement).value).toBe("14:00")
  })

  it("shows default category as work", async () => {
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    const select = wrapper.find("select")
    expect((select.element as HTMLSelectElement).value).toBe("work")
  })

  it("pushUndo called on successful add", async () => {
    mockCreateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".title-input").setValue("New Block")
    await wrapper.find("form").trigger("submit")
    await vi.dynamicImportSettled()
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "add", description: 'Added "New Block"', silent: true }),
    )
  })

  it("pushUndo NOT called on failed add", async () => {
    mockCreateBlock.mockResolvedValue({ ok: false, errors: { title: "Required" } })
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".title-input").setValue("Fail")
    await wrapper.find("form").trigger("submit")
    await vi.dynamicImportSettled()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  // Feature 0053: a block that falls fully outside the user's day window is
  // deliberately skipped server-side (409 { code: "outside_window", window }).
  // The UI must show a window-derived skip notice, NOT a generic create error,
  // and push NO undo (nothing was created).
  it("shows a window-derived skip notice (not a generic error) for an outside_window result", async () => {
    mockCreateBlock.mockResolvedValue({
      ok: false,
      code: "outside_window",
      window: { start: "08:00", end: "20:00" },
    })
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".title-input").setValue("Late night")
    await wrapper.find("form").trigger("submit")
    await vi.dynamicImportSettled()

    expect(wrapper.text()).toContain(
      "Skipped — outside your day window 08:00–20:00",
    )
    // NOT the generic failure copy.
    expect(wrapper.text()).not.toContain("Failed to create block")
    // Form stays open so the user can adjust the times.
    expect(wrapper.find(".add-form").exists()).toBe(true)
  })

  it("pushes NO undo for an outside_window skip", async () => {
    mockCreateBlock.mockResolvedValue({
      ok: false,
      code: "outside_window",
      window: { start: "08:00", end: "20:00" },
    })
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".title-input").setValue("Late night")
    await wrapper.find("form").trigger("submit")
    await vi.dynamicImportSettled()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  it("pushUndo binds scheduleDate to the date active when the request started, not when it resolved (issue #21)", async () => {
    // Simulate user navigating to a new date while createBlock is in
    // flight: without the fix, ``pushUndo`` would read ``props.date``
    // after the await and capture the new date, so undo would restore
    // 2026-04-10's snapshot onto 2026-04-11.
    let resolveCreate: (v: { ok: boolean }) => void = () => {}
    mockCreateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveCreate = res
      }),
    )
    const wrapper = mountForm({ date: "2026-04-10" })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".title-input").setValue("New Block")
    await wrapper.find("form").trigger("submit")
    // Navigate mid-flight.
    await wrapper.setProps({ date: "2026-04-11" })
    resolveCreate({ ok: true })
    await vi.dynamicImportSettled()
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "add", scheduleDate: "2026-04-10" }),
    )
  })
})
