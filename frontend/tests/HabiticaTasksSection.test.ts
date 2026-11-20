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

  it("does not paint the empty copy on the skeleton during the first load", () => {
    const wrapper = mount(HabiticaTasksSection, { props: { tasks: [], loading: true, error: null } })
    expect(wrapper.find(".habitica-skeleton").exists()).toBe(true)
    expect(wrapper.find(".habitica-empty").exists()).toBe(false)
  })

  it("keeps the last completed row mounted, locked, while it leaves", async () => {
    const wrapper = mount(HabiticaTasksSection, {
      props: { tasks: [DAILY], loading: false, error: null },
      global: { stubs: { transition: false, "transition-group": false } },
    })
    const box = wrapper.get<HTMLInputElement>('[data-testid="habitica-complete"]')
    expect(box.classes()).toContain("df-checkbox")
    box.element.checked = true
    await box.trigger("change")
    await wrapper.setProps({ tasks: [] })
    const leaving = wrapper.findAll('[data-testid="habitica-task"]')
    expect(leaving).toHaveLength(1)
    // The "df-task" TransitionGroup name is what the app.css leave rules key on.
    expect(leaving[0].classes()).toContain("df-task-leave-active")
    expect(leaving[0].get<HTMLInputElement>("input").element.checked).toBe(true)
    expect(leaving[0].get<HTMLInputElement>("input").element.disabled).toBe(true)
    expect(wrapper.emitted("complete")).toEqual([["d1"]])
  })

  it("restores a row after a failed completion as a fresh unchecked control", async () => {
    const wrapper = mount(HabiticaTasksSection, {
      props: { tasks: [DAILY, TODO], loading: false, error: null },
      global: { stubs: { transition: false, "transition-group": false } },
    })
    const box = wrapper.get<HTMLInputElement>('[data-testid="habitica-complete"]')
    box.element.checked = true
    await box.trigger("change")
    await wrapper.setProps({ tasks: [TODO] })
    await wrapper.setProps({ tasks: [DAILY, TODO], error: "Could not complete the task." })
    const live = wrapper.findAll('[data-testid="habitica-complete"]').filter((c) => !(c.element as HTMLInputElement).disabled)
    expect(live).toHaveLength(2)
    const restored = live.find((c) => c.attributes("aria-label") === "Complete Habitica task: Floss")!
    expect((restored.element as HTMLInputElement).checked).toBe(false)
    await restored.trigger("change")
    expect(wrapper.emitted("complete")).toEqual([["d1"], ["d1"]])
  })
})
