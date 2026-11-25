import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { defineComponent, h, inject, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue"
import type { TimeBlock, UserCategory } from "../src/types"
import { makeCategories } from "./helpers/schedule"
import FocusIndicatorHost from "../src/components/FocusIndicatorHost.vue"
import { ScheduleWriteCoordinatorKey, type ScheduleWriteCoordinator } from "../src/composables/scheduleWriteCoordinator"
import {
  FocusIndicatorControllerKey,
  type FocusIndicatorController,
} from "../src/composables/useFocusIndicatorController"
import {
  clearFocusIndicatorShouldBeOpen,
  readFocusIndicatorShouldBeOpen,
} from "../src/utils/focusIndicatorStorage"

const page = reactive<{
  component?: string
  props: { auth_user_id?: number | null; categories?: unknown }
}>({
  component: "Schedule",
  props: {},
})
const nowMinutes = ref<number | null>(570)
const nowDate = ref<string | null>("2026-08-12")

vi.mock("@inertiajs/vue3", () => ({
  usePage: () => page,
  createInertiaApp: vi.fn(),
}))

vi.mock("../src/composables/useNowMinutes", () => ({
  useNowMinutes: () => ({ nowMinutes, nowDate, currentHHMM: ref("") }),
}))

function makeFakeWindow() {
  const doc = document.implementation.createHTMLDocument("")
  const listeners: Record<string, Array<() => void>> = {}
  return {
    document: doc,
    addEventListener: (type: string, listener: () => void) => {
      ;(listeners[type] ||= []).push(listener)
    },
    removeEventListener: (type: string, listener: () => void) => {
      listeners[type] = (listeners[type] || []).filter((item) => item !== listener)
    },
    close: vi.fn(),
  }
}

function installFakePip(win: ReturnType<typeof makeFakeWindow>) {
  const requestWindow = vi.fn().mockResolvedValue(win)
  ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
    requestWindow,
    window: null,
  }
  return requestWindow
}

function block(): TimeBlock {
  return {
    id: 1,
    title: "Private focus",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
  }
}

let controller: FocusIndicatorController | null = null
let latestPublisherPublicationAccepted: boolean | null = null
const Publisher = defineComponent({
  props: {
    blocks: { type: Array as () => TimeBlock[], required: true },
    date: { type: String, default: "2026-08-12" },
    // Mirrors Schedule.vue: a supplied catalogue is published with the date
    // and blocks, both reactively and on unmount.
    categories: { type: Array as () => UserCategory[] | undefined, default: undefined },
  },
  setup(props) {
    controller = inject(FocusIndicatorControllerKey)!
    const generation = controller.publicationGeneration()
    const publishObservedState = () => {
      latestPublisherPublicationAccepted = controller!.publishIfGenerationMatches(
        generation,
        props.date,
        props.blocks,
        props.categories,
      )
    }
    watch(() => [props.date, props.blocks, props.categories] as const, publishObservedState, {
      immediate: true,
      deep: true,
    })
    onBeforeUnmount(() => {
      controller!.publishIfGenerationMatches(generation, props.date, props.blocks, props.categories)
    })
    return () => h("div", "schedule-like")
  },
})

const Consumer = defineComponent({
  setup() {
    controller = inject(FocusIndicatorControllerKey)!
    return () => h("div", "settings-like")
  },
})

const BLUE = "#3B82F6"
const ROSE = "#E11D48"
// jsdom normalises `background` to rgb(); only the rail's box-shadow keeps the hex.
const BLUE_RGB = "rgb(59, 130, 246)"
const ROSE_RGB = "rgb(225, 29, 72)"

function catalogWith(slug: string, color_id: UserCategory["color_id"]): UserCategory[] {
  return makeCategories().map((category) => (category.slug === slug ? { ...category, color_id } : category))
}

function railStyle(win: ReturnType<typeof makeFakeWindow>): string {
  return win.document.querySelector(".fi-rail")?.getAttribute("style") ?? ""
}

function fillStyle(win: ReturnType<typeof makeFakeWindow>): string {
  return win.document.querySelector(".fi-fill")?.getAttribute("style") ?? ""
}

/** Mount a Schedule-like publisher of the work block with `catalog` and open the fake PiP. */
async function mountPublisherWithPip(catalog: UserCategory[]) {
  page.props.auth_user_id = 1
  const win = makeFakeWindow()
  const requestWindow = installFakePip(win)
  const showingSchedule = ref(true)
  const wrapper = mount(FocusIndicatorHost, {
    slots: {
      default: () => showingSchedule.value
        ? h(Publisher, { blocks: [block()], categories: catalog })
        : h(Consumer),
    },
  })
  await controller!.focusIndicator.open()
  await flushPromises()
  return { win, requestWindow, wrapper, showingSchedule }
}

/** Open the PiP on Schedule, then navigate to `component` (Schedule unmounts). */
async function openPipThenLeaveSchedule(catalog: UserCategory[], component = "Settings") {
  const mounted = await mountPublisherWithPip(catalog)
  // Inertia swaps the page object before Vue unmounts the previous component.
  page.component = component
  mounted.showingSchedule.value = false
  await nextTick()
  return mounted
}

async function reopenPip() {
  const win = makeFakeWindow()
  installFakePip(win)
  await controller!.focusIndicator.open()
  await flushPromises()
  return win
}

beforeEach(() => {
  page.component = "Schedule"
  page.props = {}
  nowMinutes.value = 570
  nowDate.value = "2026-08-12"
  controller = null
  latestPublisherPublicationAccepted = null
  clearFocusIndicatorShouldBeOpen()
})

afterEach(() => {
  delete (window as unknown as { documentPictureInPicture?: unknown }).documentPictureInPicture
  clearFocusIndicatorShouldBeOpen()
  vi.restoreAllMocks()
})

describe("FocusIndicatorHost", () => {
  it("scopes pending schedule writes to the current root session", async () => {
    let coordinator!: ScheduleWriteCoordinator
    const Probe = defineComponent({ setup() {
      coordinator = inject(ScheduleWriteCoordinatorKey)!
      return () => h("div")
    } })
    page.props.auth_user_id = 7
    const wrapper = mount(FocusIndicatorHost, { slots: { default: () => h(Probe) } })
    const oldWrite = coordinator.track(7, "2026-08-12")
    expect(coordinator.inspect(7, "2026-08-12").pending).toHaveLength(1)
    page.component = "Login"
    await nextTick()
    expect(coordinator.inspect(7, "2026-08-12").pending).toHaveLength(0)
    page.component = "Schedule"
    oldWrite.settle("accepted", 5)
    expect(coordinator.inspect(7, "2026-08-12").floor).toBe(-1)
    wrapper.unmount()
  })
  it("can mount before Inertia initializes its page props", () => {
    Object.assign(page, { component: undefined, props: undefined })
    const wrapper = mount(FocusIndicatorHost, { slots: { default: () => h(Consumer) } })
    expect(controller!.indicatorActive.value).toBe(false)
    wrapper.unmount()
  })

  it("does not treat an uninitialized page component as logout", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    const wrapper = mount(FocusIndicatorHost, { slots: { default: () => h(Publisher, { blocks: [block()] }) } })
    await controller!.focusIndicator.open()
    await flushPromises()

    page.component = undefined
    await nextTick()

    expect(win.close).not.toHaveBeenCalled()
    expect(controller!.indicatorActive.value).toBe(true)
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)
    wrapper.unmount()
  })

  it("closes and drops retained schedule data on the definite Login transition", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    const wrapper = mount(FocusIndicatorHost, { slots: { default: () => h(Publisher, { blocks: [block()] }) } })
    await controller!.focusIndicator.open()
    await flushPromises()
    expect(controller!.indicatorActive.value).toBe(true)
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)

    page.component = "Login"
    await nextTick()

    expect(win.close).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
    expect(readFocusIndicatorShouldBeOpen()).toBe(false)
    wrapper.unmount()
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
  })

  it("does not restore the departing publisher snapshot after the root clears it for Login", async () => {
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => h(Publisher, { blocks: [block()] }) },
    })
    expect(controller!.indicatorActive.value).toBe(true)

    page.component = "Login"
    await nextTick()
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.retainedSnapshot()).toEqual({ date: "", blocks: [], categories: [] })

    wrapper.unmount()

    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
    expect(controller!.retainedSnapshot()).toEqual({ date: "", blocks: [], categories: [] })
  })

  it("refuses an ungated publish after Login (issue #212)", async () => {
    page.props.auth_user_id = 1
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => h(Publisher, { blocks: [block()] }) },
    })
    expect(controller!.indicatorActive.value).toBe(true)

    page.component = "Login"
    await nextTick()
    expect(controller!.indicatorActive.value).toBe(false)

    // Desired privacy: no public ungated write; session gate refuses current generation.
    expect("publish" in controller!).toBe(false)
    const generationAfterClear = controller!.publicationGeneration()
    expect(
      controller!.publishIfGenerationMatches(generationAfterClear, "2026-08-12", [block()]),
    ).toBe(false)
    expect(controller!.retainedSnapshot()).toEqual({ date: "", blocks: [], categories: [] })
    wrapper.unmount()
  })

  it("refuses an ungated publish after an account switch (issue #212)", async () => {
    page.props.auth_user_id = 1
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => h(Publisher, { blocks: [block()] }) },
    })
    expect(controller!.indicatorActive.value).toBe(true)
    const staleGeneration = controller!.publicationGeneration()

    page.props = { auth_user_id: 2, categories: catalogWith("work", "rose") }
    await nextTick()
    expect(controller!.indicatorActive.value).toBe(false)

    expect("publish" in controller!).toBe(false)
    expect(controller!.publishIfGenerationMatches(staleGeneration, "2026-08-12", [block()])).toBe(false)
    expect(controller!.retainedSnapshot()).toEqual({ date: "", blocks: [], categories: [] })
    wrapper.unmount()
  })

  it("returns false from publishIfGenerationMatches after Login with the post-clear generation", async () => {
    page.props.auth_user_id = 1
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => h(Publisher, { blocks: [block()] }) },
    })
    expect(controller!.indicatorActive.value).toBe(true)

    page.component = "Login"
    await nextTick()
    const generationAfterClear = controller!.publicationGeneration()
    expect(
      controller!.publishIfGenerationMatches(generationAfterClear, "2026-08-12", [block()]),
    ).toBe(false)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.retainedSnapshot().blocks).toEqual([])
    expect(controller!.retainedSnapshot().categories).toEqual([])
    wrapper.unmount()
  })

  it("closes PiP and clears on null auth_user_id alone, then refuses a current-generation publish", async () => {
    page.props.auth_user_id = 1
    const win = makeFakeWindow()
    installFakePip(win)
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => h(Publisher, { blocks: [block()] }) },
    })
    await controller!.focusIndicator.open()
    await flushPromises()
    expect(controller!.indicatorActive.value).toBe(true)
    const generationBefore = controller!.publicationGeneration()

    page.props.auth_user_id = null
    await nextTick()
    expect(win.close).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.publicationGeneration()).toBeGreaterThan(generationBefore)

    const generationAfterClear = controller!.publicationGeneration()
    expect(
      controller!.publishIfGenerationMatches(generationAfterClear, "2026-08-12", [block()]),
    ).toBe(false)
    expect(controller!.retainedSnapshot().blocks).toEqual([])
    expect(controller!.retainedSnapshot().categories).toEqual([])
    wrapper.unmount()
  })

  it("accepts observed route updates before Login and rejects them after the root clears the session", async () => {
    const scheduleState = reactive({
      date: "2026-08-12",
      blocks: [block()],
    })
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => h(Publisher, { date: scheduleState.date, blocks: scheduleState.blocks }) },
    })
    expect(latestPublisherPublicationAccepted).toBe(true)
    expect(controller!.indicatorActive.value).toBe(true)

    scheduleState.date = "2026-08-13"
    await nextTick()
    expect(latestPublisherPublicationAccepted).toBe(true)

    page.component = "Login"
    await nextTick()
    expect(controller!.indicatorActive.value).toBe(false)

    scheduleState.blocks = [{ ...block(), id: 2, title: "After boundary" }]
    await nextTick()
    expect(latestPublisherPublicationAccepted).toBe(false)
    expect(controller!.indicatorActive.value).toBe(false)

    wrapper.unmount()
    expect(controller!.indicatorActive.value).toBe(false)
  })

  it("drops the previous user's retained data even when the component stays Schedule", async () => {
    page.props.auth_user_id = 1
    const win = makeFakeWindow()
    installFakePip(win)
    const wrapper = mount(FocusIndicatorHost, { slots: { default: () => h(Publisher, { blocks: [block()] }) } })
    await controller!.focusIndicator.open()
    await flushPromises()
    expect(controller!.indicatorActive.value).toBe(true)

    page.props.auth_user_id = 2
    await nextTick()
    expect(win.close).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
    wrapper.unmount()
  })

  it("keeps one PiP open through publisher unmount and renders its later idle state", async () => {
    const win = makeFakeWindow()
    const requestWindow = installFakePip(win)
    const showingSchedule = ref(true)
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => showingSchedule.value ? h(Publisher, { blocks: [block()] }) : h(Consumer) },
    })
    await controller!.focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).not.toBeNull()

    showingSchedule.value = false
    await nextTick()
    nowMinutes.value = 600
    await nextTick()

    expect(requestWindow).toHaveBeenCalledTimes(1)
    expect(win.close).not.toHaveBeenCalled()
    // The retained 09:00–10:00 block has ended by 10:00, so the idle state is
    // the day-finished pause rather than the neutral off-today dash (0079).
    expect(win.document.querySelector('[role="progressbar"]')).toBeNull()
    expect(win.document.querySelector(".fi-pause-done")?.textContent).toBe("· day finished")
    wrapper.unmount()
  })

  it("updates the open PiP rail when the active category colour changes on Settings page props after the publisher unmounts", async () => {
    const { win, requestWindow, wrapper } = await openPipThenLeaveSchedule(catalogWith("work", "blue"))
    expect(win.close).not.toHaveBeenCalled()
    expect(railStyle(win)).toContain(BLUE)
    expect(railStyle(win)).not.toContain(ROSE)

    // Same-account router.reload({ only: ["categories", "auth_user_id"] }).
    page.props.categories = catalogWith("work", "rose")
    await nextTick()

    expect(railStyle(win)).toContain(ROSE)
    expect(railStyle(win)).toContain(ROSE_RGB)
    expect(railStyle(win)).not.toContain(BLUE)
    expect(railStyle(win)).not.toContain(BLUE_RGB)
    expect(fillStyle(win)).toContain(ROSE_RGB)
    expect(fillStyle(win)).not.toContain(BLUE_RGB)
    expect(win.close).not.toHaveBeenCalled()
    expect(requestWindow).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(true)
    expect(win.document.querySelector(".fi-root")?.textContent).toContain("Private focus")
    wrapper.unmount()
  })

  it("does not repaint the rail for a non-active colour change, then repaints for the active one", async () => {
    const { win, wrapper } = await openPipThenLeaveSchedule(catalogWith("work", "blue"))

    page.props.categories = catalogWith("personal", "amber")
    await nextTick()

    expect(railStyle(win)).toContain(BLUE)
    expect(railStyle(win)).not.toContain(ROSE)

    // A later refreshed catalogue that keeps personal amber and recolours work
    // must reach the rail, proving refreshed catalogues are copied at all.
    page.props.categories = catalogWith("personal", "amber").map((category) =>
      category.slug === "work" ? { ...category, color_id: "rose" as const } : category,
    )
    await nextTick()

    expect(railStyle(win)).toContain(ROSE)
    expect(railStyle(win)).not.toContain(BLUE)
    wrapper.unmount()
  })

  it("does not restore retained colours after Login when a new catalogue arrives", async () => {
    const { win, wrapper, showingSchedule } = await mountPublisherWithPip(catalogWith("work", "blue"))

    page.component = "Login"
    await nextTick()
    expect(win.close).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
    showingSchedule.value = false
    await nextTick()
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
    expect(controller!.retainedSnapshot().blocks).toEqual([])
    expect(controller!.retainedSnapshot().categories).toEqual([])

    // Login refuses every publication entry point; a leftover rose catalogue on
    // the page must not repopulate retained colours.
    const generationAfterClear = controller!.publicationGeneration()
    expect(
      controller!.publishIfGenerationMatches(generationAfterClear, "2026-08-12", [block()]),
    ).toBe(false)
    page.props.categories = catalogWith("work", "rose")
    await nextTick()

    const reopened = await reopenPip()
    expect(controller!.indicatorActive.value).toBe(false)
    expect(railStyle(reopened)).not.toContain(ROSE)
    wrapper.unmount()
  })

  it("does not restore the previous user's colours after an account switch", async () => {
    const { win, wrapper } = await mountPublisherWithPip(catalogWith("work", "blue"))
    expect(railStyle(win)).toContain(BLUE)
    const staleGeneration = controller!.publicationGeneration()

    // One assignment, as Inertia replaces the whole props object.
    page.props = { auth_user_id: 2, categories: catalogWith("work", "rose") }
    await nextTick()
    expect(win.close).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
    expect(controller!.retainedSnapshot().blocks).toEqual([])
    expect(controller!.retainedSnapshot().categories).toEqual([])

    expect(
      controller!.publishIfGenerationMatches(staleGeneration, "2026-08-12", [block()]),
    ).toBe(false)
    expect(controller!.retainedSnapshot().blocks).toEqual([])

    // A fresh publisher for user 2 may publish again; omit categories so the
    // leftover rose page catalogue is not adopted until it changes again.
    const freshGeneration = controller!.publicationGeneration()
    expect(
      controller!.publishIfGenerationMatches(freshGeneration, "2026-08-12", [block()]),
    ).toBe(true)
    const reopened = await reopenPip()
    expect(railStyle(reopened)).toContain(BLUE)
    expect(railStyle(reopened)).not.toContain(ROSE)
    expect(controller!.retainedSnapshot().blocks).toHaveLength(1)
    expect(controller!.retainedSnapshot().categories).toEqual([])
    wrapper.unmount()
  })

  it("does not apply a leftover catalogue after Login once the page is authenticated again", async () => {
    const { wrapper, showingSchedule } = await mountPublisherWithPip(catalogWith("work", "blue"))
    page.component = "Login"
    await nextTick()
    showingSchedule.value = false
    await nextTick()
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.retainedSnapshot().blocks).toEqual([])

    // Authenticated again, but no snapshot is retained yet.
    page.component = "Settings"
    page.props.auth_user_id = 1
    await nextTick()
    page.props.categories = catalogWith("work", "rose")
    await nextTick()

    const freshGeneration = controller!.publicationGeneration()
    expect(
      controller!.publishIfGenerationMatches(freshGeneration, "2026-08-12", [block()]),
    ).toBe(true)
    const reopened = await reopenPip()
    expect(railStyle(reopened)).toContain(BLUE)
    expect(railStyle(reopened)).not.toContain(ROSE)
    expect(controller!.retainedSnapshot().categories).toEqual([])
    wrapper.unmount()
  })

  it("does not refresh the catalogue when auth_user_id is missing", async () => {
    const { win, wrapper } = await openPipThenLeaveSchedule(catalogWith("work", "blue"))

    page.props = { categories: catalogWith("work", "rose") }
    await nextTick()

    expect(win.close).not.toHaveBeenCalled()
    expect(railStyle(win)).toContain(BLUE)
    expect(railStyle(win)).not.toContain(ROSE)
    wrapper.unmount()
  })

  it("keeps the retained catalogue when Settings omits or provides a malformed catalogue", async () => {
    const { win, wrapper } = await openPipThenLeaveSchedule(catalogWith("work", "rose"))
    expect(railStyle(win)).toContain(ROSE)

    // Give the page a valid catalogue first, so the step to undefined is a real
    // change the watcher observes (props start without categories).
    page.props.categories = catalogWith("work", "rose")
    await nextTick()
    expect(railStyle(win)).toContain(ROSE)

    page.props.categories = undefined
    await nextTick()
    expect(railStyle(win)).toContain(ROSE)
    expect(railStyle(win)).not.toContain(BLUE)

    // No sink, so invalid; copying it would turn the rail blue.
    page.props.categories = catalogWith("work", "blue").map((category) => ({ ...category, is_sink: false }))
    await nextTick()
    expect(railStyle(win)).toContain(ROSE)
    expect(railStyle(win)).not.toContain(BLUE)

    // Empty: copying it would fall back to the built-in blue.
    page.props.categories = []
    await nextTick()
    expect(railStyle(win)).toContain(ROSE)
    expect(railStyle(win)).not.toContain(BLUE)
    wrapper.unmount()
  })

  it("does not refresh the catalogue while the page component is uninitialized", async () => {
    const { win, wrapper } = await openPipThenLeaveSchedule(catalogWith("work", "blue"))

    page.component = undefined
    await nextTick()
    page.props.categories = catalogWith("work", "rose")
    await nextTick()

    expect(railStyle(win)).toContain(BLUE)
    expect(railStyle(win)).not.toContain(ROSE)
    expect(win.close).not.toHaveBeenCalled()
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)
    wrapper.unmount()
  })

  it("updates the open PiP rail from a newer catalogue on Analytics page props", async () => {
    const { win, wrapper } = await openPipThenLeaveSchedule(catalogWith("work", "blue"), "Analytics")

    page.props.categories = catalogWith("work", "rose")
    await nextTick()

    expect(railStyle(win)).toContain(ROSE)
    expect(railStyle(win)).not.toContain(BLUE)
    wrapper.unmount()
  })

  it("clears the session when Settings replaces identity and catalogue together", async () => {
    const { win, wrapper } = await openPipThenLeaveSchedule(catalogWith("work", "blue"))

    page.props = { auth_user_id: 2, categories: catalogWith("work", "rose") }
    await nextTick()

    expect(win.close).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
    wrapper.unmount()
  })

  it("uses FocusIndicatorHost in the production Inertia root composition", async () => {
    const { createInertiaRoot } = await import("../src/app")
    const App = defineComponent({ render: () => h("main", "page") })
    const root = createInertiaRoot(App, {})
    const vnode = root.render()

    expect(vnode.type).toBe(FocusIndicatorHost)
  })

  it("clears persisted chat recovery bodies on Login even when Schedule is unmounted", async () => {
    page.props.auth_user_id = 1
    sessionStorage.setItem("day-forge:chat-request:1:2027-01-15", "private frozen body")
    const wrapper = mount(FocusIndicatorHost, { slots: { default: () => h(Consumer) } })
    expect(sessionStorage.getItem("day-forge:chat-request:1:2027-01-15")).not.toBeNull()
    page.component = "Login"
    page.props.auth_user_id = null
    await nextTick()
    expect(sessionStorage.getItem("day-forge:chat-request:1:2027-01-15")).toBeNull()
    wrapper.unmount()
  })
})
