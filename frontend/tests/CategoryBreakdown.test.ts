import { describe, it, expect, vi } from "vitest"
import { mount } from "@vue/test-utils"

// CategoryBreakdown now reads `usePage().props.ui_preferences?.theme`
// to keep its color resolution reactive when the user switches themes.
// Provide a default-classic mock so the existing assertions don't need
// to know about the theming concern.
vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({ props: { ui_preferences: { theme: "classic" } } }),
}))

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

  // Feature 0053: planned bars normalise against the configurable day-window
  // span, not the historical hardcoded 1020 minutes.
  it("normalises the planned bar against a CUSTOM window span, not the 1020-minute default", () => {
    const wrapper = mount(CategoryBreakdown, {
      props: {
        planned: { work: 240, personal: 0, health: 0, other: 0 },
        completed: { work: 0, personal: 0, health: 0, other: 0 },
        // 09:00–17:00 → 480-minute span. 240/480 = 50%, whereas 240/1020 ≈ 23.5%.
        windowStart: "09:00",
        windowEnd: "17:00",
      },
    })
    const workBar = wrapper.findAll(".bar-planned")[0]
    expect(workBar.attributes("style")).toContain("width: 50%")
    // Guard against a regression to the old 1020 denominator.
    expect(workBar.attributes("style")).not.toContain("23.5")
  })

  it("falls back to the 06:00–23:00 (1020-minute) span when no window props are passed", () => {
    const wrapper = mount(CategoryBreakdown, {
      props: {
        // 510/1020 = 50% under the default span.
        planned: { work: 510, personal: 0, health: 0, other: 0 },
        completed: { work: 0, personal: 0, health: 0, other: 0 },
      },
    })
    const workBar = wrapper.findAll(".bar-planned")[0]
    expect(workBar.attributes("style")).toContain("width: 50%")
  })
})
