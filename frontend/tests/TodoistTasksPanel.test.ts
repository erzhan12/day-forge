// TodoistTasksPanel — inner content for the fixed Todoist sidebar.

import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import TodoistTasksPanel from "../src/components/TodoistTasksPanel.vue"
import type { TodoistTask } from "../src/types/todoist"

const TASK_P1: TodoistTask = {
  id: "1",
  title: "Ship the release",
  priority: 4,
  ui_priority: "P1",
  due_date: "2026-05-07",
}

const TASK_P2: TodoistTask = {
  id: "2",
  title: "Review the PR",
  priority: 3,
  ui_priority: "P2",
  due_date: "2026-05-07",
}

const TASK_P3: TodoistTask = {
  id: "3",
  title: "Water the plants",
  priority: 2,
  ui_priority: "P3",
  due_date: null,
}

const TASK_P4: TodoistTask = {
  id: "4",
  title: "Read a book",
  priority: 1,
  ui_priority: "P4",
  due_date: "2026-05-08",
}

describe("TodoistTasksPanel", () => {
  it("renders the loading skeleton when loading", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [],
        loading: true,
        error: null,
      },
    })
    expect(wrapper.find(".todoist-loading").exists()).toBe(true)
    expect(wrapper.find(".todoist-skeleton").exists()).toBe(true)
  })

  it("renders an error row with a Retry button when error is set", async () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [],
        loading: false,
        error: "Todoist service unavailable.",
      },
    })
    expect(wrapper.find(".todoist-error").exists()).toBe(true)
    const button = wrapper.find(".todoist-retry")
    expect(button.exists()).toBe(true)
    await button.trigger("click")
    expect(wrapper.emitted("retry")).toBeTruthy()
  })

  it("renders a list of tasks with the correct P1-P4 priority flag", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [TASK_P1, TASK_P2, TASK_P3, TASK_P4],
        loading: false,
        error: null,
      },
    })
    const items = wrapper.findAll('[data-testid="todoist-task"]')
    expect(items).toHaveLength(4)

    expect(items[0].text()).toContain("Ship the release")
    expect(items[0].find(".todoist-priority-dot").classes()).toContain(
      "todoist-priority-P1",
    )
    expect(items[1].text()).toContain("Review the PR")
    expect(items[1].find(".todoist-priority-dot").classes()).toContain(
      "todoist-priority-P2",
    )
    expect(items[2].text()).toContain("Water the plants")
    expect(items[2].find(".todoist-priority-dot").classes()).toContain(
      "todoist-priority-P3",
    )
    expect(items[3].text()).toContain("Read a book")
    expect(items[3].find(".todoist-priority-dot").classes()).toContain(
      "todoist-priority-P4",
    )
  })

  it("does not render a project chip, due-time, or open-in-Todoist link", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [TASK_P1, TASK_P3],
        loading: false,
        error: null,
      },
    })
    expect(wrapper.find(".todoist-project").exists()).toBe(false)
    expect(wrapper.find(".todoist-due").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("2026-05-07")
    expect(wrapper.find("a").exists()).toBe(false)
  })

  it("renders empty-state copy when no tasks", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [],
        loading: false,
        error: null,
      },
    })
    const empty = wrapper.find(".todoist-empty")
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toBe("No tasks scheduled for this day.")
  })

  it("renders a complete control per row with the correct aria-label", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [TASK_P1, TASK_P2],
        loading: false,
        error: null,
      },
    })
    const controls = wrapper.findAll('[data-testid="todoist-complete"]')
    expect(controls).toHaveLength(2)
    expect(controls[0].attributes("aria-label")).toBe(
      "Complete task: Ship the release",
    )
    expect(controls[1].attributes("aria-label")).toBe(
      "Complete task: Review the PR",
    )
  })

  it("emits complete with the task id when the control is toggled", async () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [TASK_P1, TASK_P2],
        loading: false,
        error: null,
      },
    })
    await wrapper.findAll('[data-testid="todoist-complete"]')[1].trigger("change")
    expect(wrapper.emitted("complete")).toBeTruthy()
    expect(wrapper.emitted("complete")![0]).toEqual(["2"])
  })
})
