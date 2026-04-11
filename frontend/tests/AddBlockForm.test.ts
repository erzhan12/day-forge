import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"

const mockCreateBlock = vi.fn()
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    createBlock: mockCreateBlock,
  }),
}))

import AddBlockForm from "../src/components/AddBlockForm.vue"

describe("AddBlockForm", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("shows add button initially, not the form", () => {
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10" },
    })
    expect(wrapper.find(".add-btn").exists()).toBe(true)
    expect(wrapper.find(".add-form").exists()).toBe(false)
  })

  it("shows form when add button clicked", async () => {
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10" },
    })
    await wrapper.find(".add-btn").trigger("click")
    expect(wrapper.find(".add-form").exists()).toBe(true)
    expect(wrapper.find(".add-btn").exists()).toBe(false)
  })

  it("hides form on cancel", async () => {
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10" },
    })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find(".cancel-btn").trigger("click")
    expect(wrapper.find(".add-form").exists()).toBe(false)
  })

  it("does not submit with empty title", async () => {
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10" },
    })
    await wrapper.find(".add-btn").trigger("click")
    await wrapper.find("form").trigger("submit")
    expect(mockCreateBlock).not.toHaveBeenCalled()
  })

  it("submits with valid data and resets form", async () => {
    mockCreateBlock.mockResolvedValue({ ok: true })
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10" },
    })
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
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10" },
    })
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
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10", initialStartTime: "14:00", initialEndTime: "15:00" },
    })
    // With initial times provided, form doesn't auto-show (only when they change)
    await wrapper.find(".add-btn").trigger("click")
    const startInput = wrapper.find('input[type="time"]')
    expect((startInput.element as HTMLInputElement).value).toBe("14:00")
  })

  it("shows default category as work", async () => {
    const wrapper = mount(AddBlockForm, {
      props: { date: "2026-04-10" },
    })
    await wrapper.find(".add-btn").trigger("click")
    const select = wrapper.find("select")
    expect((select.element as HTMLSelectElement).value).toBe("work")
  })
})
