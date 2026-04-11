import { describe, it, expect } from "vitest"
import { mount } from "@vue/test-utils"
import UndoToast from "../src/components/UndoToast.vue"

describe("UndoToast", () => {
  it("renders message", () => {
    const wrapper = mount(UndoToast, {
      props: { message: 'Moved "Standup" to 10:00' },
    })
    expect(wrapper.text()).toContain('Moved "Standup" to 10:00')
  })

  it("emits undo on button click", async () => {
    const wrapper = mount(UndoToast, {
      props: { message: "Test" },
    })
    await wrapper.find(".toast-undo-btn").trigger("click")
    expect(wrapper.emitted("undo")).toHaveLength(1)
  })

  it("emits dismiss on close click", async () => {
    const wrapper = mount(UndoToast, {
      props: { message: "Test" },
    })
    await wrapper.find(".toast-close-btn").trigger("click")
    expect(wrapper.emitted("dismiss")).toHaveLength(1)
  })

  it("hides undo button when actionable is false", () => {
    const wrapper = mount(UndoToast, {
      props: { message: "Undone: something", actionable: false },
    })
    expect(wrapper.find(".toast-undo-btn").exists()).toBe(false)
  })

  it("shows undo button when actionable is true", () => {
    const wrapper = mount(UndoToast, {
      props: { message: "Test", actionable: true },
    })
    expect(wrapper.find(".toast-undo-btn").exists()).toBe(true)
  })

  it("renders progress bar", () => {
    const wrapper = mount(UndoToast, {
      props: { message: "Test" },
    })
    expect(wrapper.find(".toast-progress").exists()).toBe(true)
  })
})
