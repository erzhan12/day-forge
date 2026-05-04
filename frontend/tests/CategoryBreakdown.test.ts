import { describe, it, expect } from "vitest"
import { mount } from "@vue/test-utils"
import CategoryBreakdown from "../src/components/CategoryBreakdown.vue"

describe("CategoryBreakdown", () => {
  it("renders rows for every category, even at zero minutes", () => {
    const wrapper = mount(CategoryBreakdown, {
      props: {
        planned: { work: 240, personal: 0, health: 60, other: 0 },
        completed: { work: 180, personal: 0, health: 30, other: 0 },
      },
    })
    const rows = wrapper.findAll(".row")
    // Stable order: work, personal, health, other.
    expect(rows.length).toBe(4)
    expect(rows[0].text()).toContain("Work")
    expect(rows[1].text()).toContain("Personal")
    expect(rows[2].text()).toContain("Health")
    expect(rows[3].text()).toContain("Other")
  })

  it("formats minutes as h/m correctly", () => {
    const wrapper = mount(CategoryBreakdown, {
      props: {
        planned: { work: 90, personal: 0, health: 0, other: 0 },
        completed: { work: 60, personal: 0, health: 0, other: 0 },
      },
    })
    expect(wrapper.text()).toContain("1h")
    expect(wrapper.text()).toContain("1h 30m")
  })

  it("treats a rest day (all zeros) without dividing by zero", () => {
    const wrapper = mount(CategoryBreakdown, {
      props: {
        planned: { work: 0, personal: 0, health: 0, other: 0 },
        completed: { work: 0, personal: 0, health: 0, other: 0 },
      },
    })
    // Should render without throwing; 0 minutes shows "0m planned".
    expect(wrapper.text()).toContain("0m planned")
  })
})
