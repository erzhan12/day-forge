import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import HabiticaTasksSection from "../src/components/HabiticaTasksSection.vue"
import type { HabiticaTask } from "../src/types/habitica"

const DAILY: HabiticaTask = {
  id: "d1",
  title: "Floss",
  type: "daily",
  due_date: null,
  completed: false,
}

const TODO: HabiticaTask = {
  id: "t1",
  title: "Buy milk",
  type: "todo",
  due_date: "2026-08-23",
  completed: false,
}

describe("HabiticaTasksSection", () => {
  it("renders titles without Daily/Todo type badges", () => {
    const wrapper = mount(HabiticaTasksSection, {
      props: { tasks: [DAILY, TODO], loading: false, error: null },
    })
    expect(wrapper.findAll('[data-testid="habitica-task"]')).toHaveLength(2)
    expect(wrapper.text()).toContain("Floss")
    expect(wrapper.text()).toContain("Buy milk")
    expect(wrapper.find(".habitica-type").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("Daily")
    expect(wrapper.text()).not.toContain("Todo")
  })

  it("keeps loaded tasks visible and actionable beside a refresh error", async () => {
    const wrapper = mount(HabiticaTasksSection, {
      props: { tasks: [DAILY], loading: false, error: "Habitica service unavailable." },
    })
    expect(wrapper.find(".habitica-error").text()).toContain("unavailable")
    expect(wrapper.findAll('[data-testid="habitica-task"]')).toHaveLength(1)
    expect(wrapper.find(".habitica-empty").exists()).toBe(false)
    await wrapper.find(".habitica-retry").trigger("click")
    await wrapper.find('[data-testid="habitica-complete"]').trigger("change")
    expect(wrapper.emitted("retry")).toHaveLength(1)
    expect(wrapper.emitted("complete")).toEqual([["d1"]])
  })

  it("shows only the error when a new date has no loaded tasks", () => {
    const wrapper = mount(HabiticaTasksSection, {
      props: { tasks: [], loading: false, error: "Habitica service unavailable." },
    })
    expect(wrapper.find(".habitica-error").exists()).toBe(true)
    expect(wrapper.find(".habitica-empty").exists()).toBe(false)
    expect(wrapper.find(".habitica-skeleton").exists()).toBe(false)
  })

  it("keeps loaded tasks visible during a background refresh", () => {
    const wrapper = mount(HabiticaTasksSection, {
      props: { tasks: [TODO], loading: true, error: null },
    })
    expect(wrapper.findAll('[data-testid="habitica-task"]')).toHaveLength(1)
    expect(wrapper.find(".habitica-skeleton").exists()).toBe(false)
  })
})
