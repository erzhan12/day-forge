import { describe, it, expect } from "vitest"
import { mount } from "@vue/test-utils"
import StreakCounter from "../src/components/StreakCounter.vue"

describe("StreakCounter", () => {
  it("hides emoji when streak is 0", () => {
    const wrapper = mount(StreakCounter, {
      props: { streak: 0, threshold: 0.8 },
    })
    expect(wrapper.find(".emoji").exists()).toBe(false)
    expect(wrapper.text()).toContain("0-day streak")
  })

  it("renders emoji when streak is positive", () => {
    const wrapper = mount(StreakCounter, {
      props: { streak: 12, threshold: 0.8 },
    })
    expect(wrapper.find(".emoji").exists()).toBe(true)
    expect(wrapper.text()).toContain("12-day streak")
  })

  it("tooltip reflects threshold", () => {
    const wrapper = mount(StreakCounter, {
      props: { streak: 5, threshold: 0.7 },
    })
    expect(wrapper.attributes("title")).toBe(
      "Days with ≥ 70% completion",
    )
  })
})
