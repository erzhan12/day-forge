import { describe, it, expect } from "vitest"
import { mount } from "@vue/test-utils"
import CompletionBar from "../src/components/CompletionBar.vue"

describe("CompletionBar", () => {
  it("renders the rest-day message when planned is 0", () => {
    const wrapper = mount(CompletionBar, {
      props: { completed: 0, planned: 0 },
    })
    expect(wrapper.text()).toContain("Rest day")
    expect(wrapper.find(".track").exists()).toBe(false)
  })

  it("renders the ratio + percent + bar fill when planned > 0", () => {
    const wrapper = mount(CompletionBar, {
      props: { completed: 3, planned: 4 },
    })
    expect(wrapper.text()).toContain("3/4")
    expect(wrapper.text()).toContain("75%")
    const fill = wrapper.find(".fill")
    expect(fill.exists()).toBe(true)
    expect(fill.attributes("style")).toContain("75%")
  })

  it("rounds the percent to the nearest int", () => {
    const wrapper = mount(CompletionBar, {
      props: { completed: 1, planned: 3 },
    })
    expect(wrapper.text()).toContain("33%")
  })
})
