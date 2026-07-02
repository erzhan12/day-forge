// TodoistSidebar tests — toggle shell mirroring ChatSidebar on the left.

import { afterEach, describe, expect, it } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"

import TodoistSidebar from "../src/components/TodoistSidebar.vue"

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

function mountSidebar(open: boolean) {
  return mount(TodoistSidebar, {
    props: {
      tasks: [{ id: "1", title: "A task", priority: 1, ui_priority: "P4", due_date: null }],
      loading: false,
      error: null,
      open,
      "onUpdate:open": (v: boolean) => {
        wrapper?.setProps({ open: v })
      },
    },
    attachTo: document.body,
  })
}

describe("TodoistSidebar — open state", () => {
  it("names the complementary landmark", () => {
    wrapper = mountSidebar(true)
    expect(wrapper.find('[data-testid="todoist-sidebar"]').attributes("aria-label"))
      .toBe("Todoist tasks")
  })

  it("renders the task panel and body when open", () => {
    wrapper = mountSidebar(true)
    expect(wrapper.find('[data-testid="todoist-panel"]').exists()).toBe(true)
    expect(wrapper.find("#todoist-sidebar-body").exists()).toBe(true)
  })

  it("toggle button has aria-expanded=true when open", () => {
    wrapper = mountSidebar(true)
    const btn = wrapper.find('[data-testid="todoist-sidebar-toggle"]')
    expect(btn.attributes("aria-expanded")).toBe("true")
    expect(btn.attributes("aria-label")).toBe("Collapse Todoist panel")
  })
})

describe("TodoistSidebar — collapsed state", () => {
  it("does NOT render the task panel when collapsed", () => {
    wrapper = mountSidebar(false)
    expect(wrapper.find('[data-testid="todoist-panel"]').exists()).toBe(false)
  })

  it("toggle button has aria-expanded=false when collapsed", () => {
    wrapper = mountSidebar(false)
    const btn = wrapper.find('[data-testid="todoist-sidebar-toggle"]')
    expect(btn.attributes("aria-expanded")).toBe("false")
    expect(btn.attributes("aria-label")).toBe("Expand Todoist panel")
  })
})

describe("TodoistSidebar — toggle behavior", () => {
  it("emits update:open false when collapsing", async () => {
    wrapper = mountSidebar(true)
    await wrapper.find('[data-testid="todoist-sidebar-toggle"]').trigger("click")
    expect(wrapper.emitted("update:open")![0]).toEqual([false])
  })

  it("emits update:open true when expanding", async () => {
    wrapper = mountSidebar(false)
    await wrapper.find('[data-testid="todoist-sidebar-toggle"]').trigger("click")
    expect(wrapper.emitted("update:open")![0]).toEqual([true])
  })
})

describe("TodoistSidebar — refresh button (PART B)", () => {
  it("renders the Refresh button when open and emits refresh on click", async () => {
    wrapper = mountSidebar(true)
    const btn = wrapper.find('[data-testid="todoist-sidebar-refresh"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes("aria-label")).toBe("Refresh Todoist tasks")
    await btn.trigger("click")
    expect(wrapper.emitted("refresh")).toBeTruthy()
  })

  it("hides the Refresh button when collapsed", () => {
    wrapper = mountSidebar(false)
    expect(wrapper.find('[data-testid="todoist-sidebar-refresh"]').exists()).toBe(false)
  })
})

describe("TodoistSidebar — complete passthrough (PART A)", () => {
  it("propagates a complete event from the panel up through the sidebar", async () => {
    wrapper = mountSidebar(true)
    await wrapper.find('[data-testid="todoist-complete"]').trigger("change")
    expect(wrapper.emitted("complete")).toBeTruthy()
    expect(wrapper.emitted("complete")![0]).toEqual(["1"])
  })
})

// Feature 0022: the sidebar can host a calendar panel (default slot) and can
// render with Todoist absent (calendar-only user).
function mountSidebarWith(props: Record<string, unknown>, slot?: string) {
  return mount(TodoistSidebar, {
    props: {
      tasks: [],
      loading: false,
      error: null,
      open: true,
      "onUpdate:open": () => {},
      ...props,
    },
    slots: slot ? { default: slot } : {},
    attachTo: document.body,
  })
}

describe("TodoistSidebar — showTasks / showExtra (feature 0022)", () => {
  it("hides the task panel + refresh and titles 'Calendar' when showTasks=false", () => {
    wrapper = mountSidebarWith({ showTasks: false, showExtra: true })
    expect(wrapper.find('[data-testid="todoist-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="todoist-sidebar-refresh"]').exists()).toBe(false)
    expect(wrapper.find(".todoist-sidebar-title").text()).toBe("Calendar")
  })

  it("still titles 'Todoist' and shows the task panel when showTasks=true", () => {
    wrapper = mountSidebarWith({ showTasks: true })
    expect(wrapper.find(".todoist-sidebar-title").text()).toBe("Todoist")
    expect(wrapper.find('[data-testid="todoist-panel"]').exists()).toBe(true)
  })

  it("renders slotted calendar content under .todoist-sidebar-extra when showExtra=true", () => {
    wrapper = mountSidebarWith(
      { showTasks: true, showExtra: true },
      '<div class="stub-cal">CAL</div>',
    )
    const extra = wrapper.find(".todoist-sidebar-extra")
    expect(extra.exists()).toBe(true)
    expect(extra.find(".stub-cal").text()).toBe("CAL")
  })

  it("omits .todoist-sidebar-extra when showExtra=false", () => {
    wrapper = mountSidebarWith(
      { showTasks: true, showExtra: false },
      '<div class="stub-cal">CAL</div>',
    )
    expect(wrapper.find(".todoist-sidebar-extra").exists()).toBe(false)
  })

  it("titles + labels reflect BOTH sections when showTasks && showExtra", () => {
    wrapper = mountSidebarWith(
      { showTasks: true, showExtra: true },
      '<div class="stub-cal">CAL</div>',
    )
    expect(wrapper.find(".todoist-sidebar-title").text()).toBe("Tasks & Calendar")
    // Landmark + collapse toggle read the combined content, not just Todoist.
    expect(
      wrapper.find('[data-testid="todoist-sidebar"]').attributes("aria-label"),
    ).toBe("Tasks and Calendar")
    expect(
      wrapper.find('[data-testid="todoist-sidebar-toggle"]').attributes("aria-label"),
    ).toBe("Collapse Tasks & Calendar panel")
  })
})
