import { afterEach, describe, expect, it } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"

import ExternalTasksSidebar from "../src/components/ExternalTasksSidebar.vue"

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

function baseProps(open: boolean) {
  return {
    todoistTasks: [
      { id: "todo-1", title: "A task", priority: 1, ui_priority: "P4", due_date: null },
    ],
    todoistLoading: false,
    todoistError: null,
    showTodoist: true,
    habiticaTasks: [
      { id: "hab-1", title: "Daily", type: "daily", due_date: null, completed: false },
    ],
    habiticaLoading: false,
    habiticaError: null,
    showHabitica: false,
    showExtra: false,
    open,
    "onUpdate:open": (v: boolean) => {
      wrapper?.setProps({ open: v })
    },
  }
}

function mountSidebar(open: boolean, props: Record<string, unknown> = {}) {
  return mount(ExternalTasksSidebar, {
    props: { ...baseProps(open), ...props },
    attachTo: document.body,
  })
}

describe("ExternalTasksSidebar — open state", () => {
  it("names the task landmark", () => {
    wrapper = mountSidebar(true)
    expect(wrapper.find('[data-testid="todoist-sidebar"]').attributes("aria-label"))
      .toBe("External tasks")
  })

  it("renders Todoist section and body when open", () => {
    wrapper = mountSidebar(true)
    expect(wrapper.find('[data-testid="todoist-panel"]').exists()).toBe(true)
    expect(wrapper.find("#external-tasks-sidebar-body").exists()).toBe(true)
  })

  it("toggle button has aria-expanded=true when open", () => {
    wrapper = mountSidebar(true)
    const btn = wrapper.find('[data-testid="todoist-sidebar-toggle"]')
    expect(btn.attributes("aria-expanded")).toBe("true")
    expect(btn.attributes("aria-label")).toBe("Collapse Tasks panel")
  })
})

describe("ExternalTasksSidebar — collapsed state", () => {
  it("does not render task panels when collapsed", () => {
    wrapper = mountSidebar(false, { showHabitica: true })
    expect(wrapper.find('[data-testid="todoist-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="habitica-panel"]').exists()).toBe(false)
  })

  it("emits update:open true when expanding", async () => {
    wrapper = mountSidebar(false)
    await wrapper.find('[data-testid="todoist-sidebar-toggle"]').trigger("click")
    expect(wrapper.emitted("update:open")![0]).toEqual([true])
  })
})

describe("ExternalTasksSidebar — refresh and source routing", () => {
  it("emits refresh from the global refresh button", async () => {
    wrapper = mountSidebar(true)
    const btn = wrapper.find('[data-testid="todoist-sidebar-refresh"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes("aria-label")).toBe("Refresh external tasks")
    await btn.trigger("click")
    expect(wrapper.emitted("refresh")).toBeTruthy()
  })

  it("routes Todoist complete through todoistComplete", async () => {
    // Mount with BOTH sections present, otherwise the negative assertion is
    // vacuous — with showHabitica false there is no Habitica section that
    // could have emitted, so mis-routing would be unobservable here.
    wrapper = mountSidebar(true, { showHabitica: true })
    await wrapper.find('[data-testid="todoist-complete"]').trigger("change")
    expect(wrapper.emitted("todoistComplete")![0]).toEqual(["todo-1"])
    expect(wrapper.emitted("habiticaComplete")).toBeUndefined()
  })

  it("routes Habitica complete through habiticaComplete", async () => {
    wrapper = mountSidebar(true, { showHabitica: true })
    await wrapper.find('[data-testid="habitica-complete"]').trigger("change")
    expect(wrapper.emitted("habiticaComplete")![0]).toEqual(["hab-1"])
    expect(wrapper.emitted("todoistComplete")).toBeUndefined()
  })
})

describe("ExternalTasksSidebar — show sections", () => {
  it("renders calendar-only title when no task source is visible", () => {
    wrapper = mountSidebar(true, { showTodoist: false, showExtra: true })
    expect(wrapper.find('[data-testid="todoist-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="todoist-sidebar-refresh"]').exists()).toBe(false)
    expect(wrapper.find(".external-tasks-sidebar-title").text()).toBe("Calendar")
  })

  it("renders both task sections with static counts", () => {
    wrapper = mountSidebar(true, { showHabitica: true })
    const headers = wrapper.findAll(".external-tasks-section-header")
    expect(headers.map((h) => h.text())).toEqual(["Todoist1", "Habitica1"])
  })

  it("renders slotted calendar content below task sections", () => {
    wrapper = mount(ExternalTasksSidebar, {
      props: { ...baseProps(true), showExtra: true },
      slots: { default: '<div class="stub-cal">CAL</div>' },
      attachTo: document.body,
    })
    const extra = wrapper.find(".external-tasks-sidebar-extra")
    expect(extra.exists()).toBe(true)
    expect(extra.find(".stub-cal").text()).toBe("CAL")
  })
})
