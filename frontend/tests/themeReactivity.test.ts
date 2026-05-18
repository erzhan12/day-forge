import { describe, it, expect, vi, beforeEach } from "vitest"
import { ref, nextTick } from "vue"
import { mount } from "@vue/test-utils"

// Reactive page-props ref so each test can mutate the theme and observe
// the rendered color update.
const mocks = vi.hoisted(() => {
  const { ref } = require("vue") as typeof import("vue")
  return {
    pagePropsRef: ref<{ ui_preferences?: { theme?: string } }>({
      ui_preferences: { theme: "classic" },
    }),
  }
})

vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({
    get props() {
      return mocks.pagePropsRef.value
    },
  }),
}))

vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({ updateBlock: vi.fn(), deleteBlock: vi.fn() }),
}))

import TimeBlock from "../src/components/TimeBlock.vue"
import SkippedTasks from "../src/components/SkippedTasks.vue"
import { categoryColors } from "../src/utils/categoryColors"

const { pagePropsRef } = mocks

beforeEach(() => {
  pagePropsRef.value = { ui_preferences: { theme: "classic" } }
  delete document.documentElement.dataset.theme
})

describe("TimeBlock theme reactivity (health override)", () => {
  it("updates the left-border color when ui_preferences.theme changes", async () => {
    const block = {
      id: 1,
      title: "Run",
      start_time: "07:00",
      end_time: "08:00",
      category: "health" as const,
      is_completed: false,
      sort_order: 0,
    }
    const wrapper = mount(TimeBlock, {
      props: { block, date: "2026-04-07" },
    })
    // Find the block container with the inline border style. Most
    // shapes of TimeBlock render the colored border on the root element.
    const initial = wrapper.attributes("style") ?? ""
    // Classic applies the #059669 override on `health`.
    expect(initial.toLowerCase()).toContain("border-left-color: rgb(5, 150, 105)")

    // Switch to Strategic — base palette (#10B981) wins.
    pagePropsRef.value = { ui_preferences: { theme: "strategic" } }
    await nextTick()
    const after = wrapper.attributes("style") ?? ""
    expect(after.toLowerCase()).toContain("border-left-color: rgb(16, 185, 129)")
    // Sanity: the new color comes from the base, which is what
    // `categoryColors.health` holds.
    expect(categoryColors.health).toBe("#10B981")
  })
})

describe("SkippedTasks theme reactivity (health override)", () => {
  it("updates the dot color when ui_preferences.theme changes", async () => {
    // Pick a block in the past so it qualifies as "skipped" today —
    // SkippedTasks filters to past blocks that were not completed.
    const past = "2026-04-07"
    const block = {
      id: 1,
      title: "Run",
      start_time: "07:00",
      end_time: "08:00",
      category: "health" as const,
      is_completed: false,
      sort_order: 0,
    }
    const wrapper = mount(SkippedTasks, {
      props: { blocks: [block], date: past },
      attachTo: document.body,
    })

    const dot = wrapper.find(".dot, [data-testid='skipped-dot']")
    // If component renders dots with a `.dot` class:
    const initialStyle = dot.exists()
      ? dot.attributes("style") ?? ""
      : (wrapper.html() ?? "")
    expect(initialStyle.toLowerCase()).toContain("rgb(5, 150, 105)")

    pagePropsRef.value = { ui_preferences: { theme: "strategic" } }
    await nextTick()
    const afterStyle = dot.exists()
      ? dot.attributes("style") ?? ""
      : (wrapper.html() ?? "")
    expect(afterStyle.toLowerCase()).toContain("rgb(16, 185, 129)")
    wrapper.unmount()
  })
})
