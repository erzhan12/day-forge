// TodoistTasksPanel — inner content for the fixed Todoist sidebar.

import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

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
    expect(wrapper.find(".todoist-empty").exists()).toBe(false)
    expect(wrapper.find(".todoist-skeleton").exists()).toBe(false)
  })

  it("keeps loaded tasks visible and actionable beside a refresh error", async () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: { tasks: [TASK_P1], loading: false, error: "Todoist service unavailable." },
    })
    expect(wrapper.find(".todoist-error").text()).toContain("unavailable")
    expect(wrapper.findAll('[data-testid="todoist-task"]')).toHaveLength(1)
    expect(wrapper.find(".todoist-empty").exists()).toBe(false)
    await wrapper.find(".todoist-retry").trigger("click")
    await wrapper.find('[data-testid="todoist-complete"]').trigger("change")
    expect(wrapper.emitted("retry")).toHaveLength(1)
    expect(wrapper.emitted("complete")).toEqual([["1"]])
  })

  it("keeps loaded tasks visible during a background refresh", () => {
    const wrapper = mount(TodoistTasksPanel, {
      props: { tasks: [TASK_P1], loading: true, error: null },
    })
    expect(wrapper.findAll('[data-testid="todoist-task"]')).toHaveLength(1)
    expect(wrapper.find(".todoist-skeleton").exists()).toBe(false)
  })

  it("renders a list of tasks without a priority flag", () => {
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
    expect(items[1].text()).toContain("Review the PR")
    expect(items[2].text()).toContain("Water the plants")
    expect(items[3].text()).toContain("Read a book")
    expect(wrapper.find(".todoist-priority-dot").exists()).toBe(false)
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

  it("does not paint the empty copy on the skeleton during the first load", () => {
    const wrapper = mount(TodoistTasksPanel, { props: { tasks: [], loading: true, error: null } })
    expect(wrapper.find(".todoist-skeleton").exists()).toBe(true)
    expect(wrapper.find(".todoist-empty").exists()).toBe(false)
  })

  it("uses the shared checkbox with the Todoist provider colour", () => {
    const wrapper = mount(TodoistTasksPanel, { props: { tasks: [TASK_P1], loading: false, error: null } })
    expect(wrapper.get('[data-testid="todoist-complete"]').classes()).toContain("df-checkbox")
  })

  describe("leave animation", () => {
    const unstubbed = { global: { stubs: { transition: false, "transition-group": false } } }

    it("keeps the last completed row mounted, locked, while it leaves", async () => {
      const wrapper = mount(TodoistTasksPanel, { props: { tasks: [TASK_P1], loading: false, error: null }, ...unstubbed })
      const box = wrapper.get<HTMLInputElement>('[data-testid="todoist-complete"]')
      box.element.checked = true
      await box.trigger("change")
      await wrapper.setProps({ tasks: [] })
      const leaving = wrapper.findAll('[data-testid="todoist-task"]')
      expect(leaving).toHaveLength(1)
      // The "df-task" TransitionGroup name is what the app.css leave rules key on.
      expect(leaving[0].classes()).toContain("df-task-leave-active")
      expect(leaving[0].attributes("aria-hidden")).toBe("true")
      // A disabled control takes no clicks or Space, so it cannot emit again.
      expect(leaving[0].get<HTMLInputElement>("input").element.disabled).toBe(true)
      expect(wrapper.emitted("complete")).toEqual([["1"]])
    })

    it("restores a row after a failed completion as a fresh unchecked control", async () => {
      const wrapper = mount(TodoistTasksPanel, { props: { tasks: [TASK_P1, TASK_P2], loading: false, error: null }, ...unstubbed })
      const box = wrapper.get<HTMLInputElement>('[data-testid="todoist-complete"]')
      box.element.checked = true
      await box.trigger("change")
      await wrapper.setProps({ tasks: [TASK_P2] })
      await wrapper.setProps({ tasks: [TASK_P1, TASK_P2], error: "Could not complete the task." })
      const live = wrapper.findAll('[data-testid="todoist-complete"]').filter((c) => !(c.element as HTMLInputElement).disabled)
      expect(live).toHaveLength(2)
      const restored = live.find((c) => c.attributes("aria-label") === "Complete task: Ship the release")!
      expect((restored.element as HTMLInputElement).checked).toBe(false)
      await restored.trigger("change")
      expect(wrapper.emitted("complete")).toEqual([["1"], ["1"]])
    })
  })

  it("animates only a ticked row; rows leaving for other reasons go at once", () => {
    // jsdom runs no CSS transitions, so pin the stylesheet contract instead.
    const css = readFileSync(resolve(__dirname, "..", "src/app.css"), "utf-8")
    const base = /\.df-task-leave-active \{([^}]*)\}/.exec(css)![1]
    expect(base).not.toContain("transition")
    expect(css).toContain(".df-task-leave-active:has(.df-checkbox:checked) {\n  transition: opacity 250ms ease;")
    expect(css).toContain(".df-task-leave-active:has(.df-checkbox:checked) .df-task-title {")
    expect(css).toMatch(/\.df-task-leave-active:has\(\.df-checkbox:checked\) \.df-task-title \{[^}]*text-decoration: line-through;/)
    expect(css).toMatch(/\.df-task-leave-to:has\(\.df-checkbox:checked\) \{[^}]*opacity: 0;/)
    const reduced = css.slice(css.lastIndexOf("@media (prefers-reduced-motion: reduce)"))
    expect(reduced).toMatch(/\.df-task-leave-active:has\(\.df-checkbox:checked\) \{\s*transition: none;/)
  })
})
