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
})
