import { afterEach, describe, expect, it } from "vitest"
import { nextTick } from "vue"
import { mount, VueWrapper } from "@vue/test-utils"

import ExternalRail4a from "../src/components/ExternalRail4a.vue"
import type { TodoistTask } from "../src/types/todoist"

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

const TASK_A: TodoistTask = {
  id: "todo-1",
  title: "A task",
  priority: 1,
  ui_priority: "P4",
  due_date: null,
}
const TASK_B: TodoistTask = {
  id: "todo-2",
  title: "B task",
  priority: 1,
  ui_priority: "P4",
  due_date: null,
}
const TASK_C: TodoistTask = {
  id: "todo-3",
  title: "C task",
  priority: 1,
  ui_priority: "P4",
  due_date: null,
}

function baseProps() {
  return {
    activeDate: "2026-08-22",
    open: true,
    "onUpdate:open": (v: boolean) => {
      wrapper?.setProps({ open: v })
    },
    todoistTasks: [] as TodoistTask[],
    todoistLoading: false,
    todoistError: null as string | null,
    showTodoist: true,
    habiticaTasks: [],
    habiticaLoading: false,
    habiticaError: null,
    showHabitica: false,
    showCalendars: false,
    events: [],
    eventsLoading: false,
    eventErrors: [],
    accountErrors: [],
    externalConnected: false,
    nowMinutes: null,
  }
}

function mountRail(props: Record<string, unknown> = {}) {
  wrapper = mount(ExternalRail4a, {
    props: { ...baseProps(), ...props },
    attachTo: document.body,
  })
  return wrapper
}

function progressText(): string {
  return wrapper!.get('[data-testid="todoist-session-progress"]').text()
}

async function commitTodoistLoad(tasks: TodoistTask[], error: string | null = null) {
  await wrapper!.setProps({ todoistLoading: true, todoistError: null })
  await nextTick()
  await wrapper!.setProps({ todoistLoading: false, todoistTasks: tasks, todoistError: error })
  await nextTick()
}

describe("ExternalRail4a session baseline", () => {
  it("does not lock the idle loading=false empty list as the denominator", async () => {
    mountRail({ todoistLoading: false, todoistTasks: [] })
    expect(progressText()).toBe("0 left")

    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    expect(progressText()).toBe("0 completed this session / 3")
  })

  it("treats an empty successful load as baseline 0, not missing", async () => {
    mountRail()
    await commitTodoistLoad([])
    expect(progressText()).toBe("0 completed this session / 0")
  })

  it("captures a warm mount that already has rows (theme switch)", async () => {
    mountRail({ todoistLoading: false, todoistTasks: [TASK_A, TASK_B] })
    await nextTick()
    expect(progressText()).toBe("0 completed this session / 2")
  })

  it("does not capture a failed fetch; recaptures on the next success", async () => {
    mountRail()
    await commitTodoistLoad([], "Todoist service unavailable. Try again later.")
    expect(progressText()).toBe("0 left")

    await commitTodoistLoad([TASK_A, TASK_B])
    expect(progressText()).toBe("0 completed this session / 2")
  })

  it("resets on date change and waits for the new date's commit, not the stale list", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    expect(progressText()).toBe("0 completed this session / 3")

    await wrapper!.setProps({ activeDate: "2026-08-23" })
    await nextTick()
    expect(progressText()).toBe("0 left")

    await commitTodoistLoad([TASK_A])
    expect(progressText()).toBe("0 completed this session / 1")
  })

  it("accepts the in-flight commit when the date changes during a load", async () => {
    mountRail({ todoistLoading: true, todoistTasks: [TASK_A, TASK_B, TASK_C] })
    expect(progressText()).toBe("0 left")

    await wrapper!.setProps({ activeDate: "2026-08-23" })
    await nextTick()
    expect(progressText()).toBe("0 left")

    await wrapper!.setProps({
      todoistLoading: false,
      todoistTasks: [TASK_A],
      todoistError: null,
    })
    await nextTick()
    expect(progressText()).toBe("0 completed this session / 1")
  })

  it("counts a row that vanishes after refresh as completed this session", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await commitTodoistLoad([TASK_A, TASK_B])
    expect(progressText()).toBe("1 completed this session / 3")
  })

  it("keeps the session denominator when the last remaining task vanishes", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await commitTodoistLoad([])
    expect(progressText()).toBe("3 completed this session / 3")
  })

  it("counts completing the last task without a loading cycle", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await wrapper!.setProps({ todoistTasks: [] })
    await nextTick()
    expect(progressText()).toBe("3 completed this session / 3")
  })

  it("does not keep an empty-day baseline when tasks later appear", async () => {
    mountRail()
    await commitTodoistLoad([])
    expect(progressText()).toBe("0 completed this session / 0")

    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    expect(progressText()).toBe("0 completed this session / 3")

    await wrapper!.setProps({ todoistTasks: [] })
    await nextTick()
    expect(progressText()).toBe("3 completed this session / 3")
  })

  it("counts an in-app complete once the parent drops the row", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B])
    await wrapper!.findAll('[data-testid="todoist-complete"]')[0].trigger("change")
    await wrapper!.setProps({ todoistTasks: [TASK_B] })
    await nextTick()
    expect(progressText()).toBe("1 completed this session / 2")
    expect(wrapper!.emitted("todoistComplete")![0]).toEqual(["todo-1"])
  })

  it("still counts a baseline id that left even if a new task arrives in the same refresh", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B])
    await commitTodoistLoad([TASK_B, TASK_C])
    expect(progressText()).toBe("1 completed this session / 3")
  })

  it("grows the denominator when a new task appears after the session was already 1/1", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A])
    await commitTodoistLoad([])
    expect(progressText()).toBe("1 completed this session / 1")

    await commitTodoistLoad([TASK_B])
    expect(progressText()).toBe("1 completed this session / 2")
  })

  it("does not treat an in-flight refresh as wiping the remaining set", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await wrapper!.setProps({ todoistLoading: true })
    await nextTick()
    expect(progressText()).toBe("0 completed this session / 3")
  })

  it("counts a Habitica daily that disappears after refresh", async () => {
    const dailyA = { id: "hab-1", title: "Floss", type: "daily" as const, due_date: null, completed: false }
    const dailyB = { id: "hab-2", title: "Stretch", type: "daily" as const, due_date: null, completed: false }
    mountRail({ showHabitica: true, showTodoist: false })
    await wrapper!.setProps({ habiticaLoading: true, habiticaError: null })
    await nextTick()
    await wrapper!.setProps({
      habiticaLoading: false,
      habiticaTasks: [dailyA, dailyB],
      habiticaError: null,
    })
    await nextTick()
    expect(wrapper!.get('[data-testid="habitica-session-progress"]').text()).toBe(
      "0 completed this session / 2",
    )

    await wrapper!.setProps({ habiticaLoading: true })
    await nextTick()
    await wrapper!.setProps({
      habiticaLoading: false,
      habiticaTasks: [dailyB],
      habiticaError: null,
    })
    await nextTick()
    expect(wrapper!.get('[data-testid="habitica-session-progress"]').text()).toBe(
      "1 completed this session / 2",
    )
  })
})

describe("ExternalRail4a section layout", () => {
  it("keeps task sections as siblings and pins the calendar last", () => {
    mountRail({ showHabitica: true, showCalendars: true, externalConnected: true })
    const content = wrapper!.get(".rail-content")
    const sections = content.findAll(":scope > section")
    expect(sections).toHaveLength(3)
    expect(sections[0].classes()).toContain("task-section")
    expect(sections[1].classes()).toContain("task-section")
    expect(sections[2].classes()).toContain("calendar-section")
    expect(content.element.lastElementChild).toBe(sections[2].element)
  })
})
