import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { defineComponent, h, inject, nextTick, onBeforeUnmount, reactive, ref, watch } from "vue"
import type { TimeBlock } from "../src/types"
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
  props: { auth_user_id?: number | null }
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
  },
  setup(props) {
    controller = inject(FocusIndicatorControllerKey)!
    const generation = controller.publicationGeneration()
    const publishObservedState = () => {
      latestPublisherPublicationAccepted = controller!.publishIfGenerationMatches(
        generation,
        props.date,
        props.blocks,
      )
    }
    watch(() => [props.date, props.blocks] as const, publishObservedState, { immediate: true, deep: true })
    onBeforeUnmount(() => {
      controller!.publishIfGenerationMatches(generation, props.date, props.blocks)
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

    wrapper.unmount()

    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.indicatorNextBlock.value).toBeNull()
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

  it("uses FocusIndicatorHost in the production Inertia root composition", async () => {
    const { createInertiaRoot } = await import("../src/app")
    const App = defineComponent({ render: () => h("main", "page") })
    const root = createInertiaRoot(App, {})
    const vnode = root.render()

    expect(vnode.type).toBe(FocusIndicatorHost)
  })
})
