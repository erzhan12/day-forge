// Render snapshots for TodoistTasksPanel.vue across its states:
// hidden (not connected / status unknown), loading (skeleton), error,
// populated (priority flags), empty.

import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import TodoistTasksPanel from "../src/components/TodoistTasksPanel.vue"
import type { TodoistTask } from "../src/types/todoist"

// priority 4 -> P1 (highest), 1 -> P4. ui_priority = "P" + str(5 - priority).
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
  it("renders nothing when not connected", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [],
        loading: false,
        error: null,
        connected: false,
        statusKnown: true,
      },
    })
    expect(wrapper.find("section.todoist-tasks").exists()).toBe(false)
  })

  it("renders nothing until status is known", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [],
        loading: false,
        error: null,
        connected: true,
        statusKnown: false,
      },
    })
    expect(wrapper.find("section.todoist-tasks").exists()).toBe(false)
  })

  it("renders the loading skeleton when loading", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [],
        loading: true,
        error: null,
        connected: true,
        statusKnown: true,
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
        connected: true,
        statusKnown: true,
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
        connected: true,
        statusKnown: true,
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

  it("uses the Todoist header label and an accessible region label", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [TASK_P1],
        loading: false,
        error: null,
        connected: true,
        statusKnown: true,
      },
    })
    const region = wrapper.find('[aria-label="Todoist tasks"]')
    expect(region.exists()).toBe(true)
    expect(wrapper.find(".todoist-title").text()).toBe("Todoist")
  })

  it("does not render a project chip, due-time, or open-in-Todoist link", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [TASK_P1, TASK_P3],
        loading: false,
        error: null,
        connected: true,
        statusKnown: true,
      },
    })
    // No project chip / project name.
    expect(wrapper.find(".todoist-project").exists()).toBe(false)
    // No due-time rendered (date dropped from display per V1 scope).
    expect(wrapper.find(".todoist-due").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("2026-05-07")
    // No open-in-Todoist link.
    expect(wrapper.find("a").exists()).toBe(false)
  })

  it("renders empty-state copy when connected but no tasks", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: {
        tasks: [],
        loading: false,
        error: null,
        connected: true,
        statusKnown: true,
      },
    })
    const empty = wrapper.find(".todoist-empty")
    expect(empty.exists()).toBe(true)
    expect(empty.text()).toBe("No tasks scheduled for this day.")
  })
})
