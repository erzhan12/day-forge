import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { defineComponent, h, inject, nextTick, reactive, ref } from "vue"
import type { TimeBlock } from "../src/types"
import FocusIndicatorHost from "../src/components/FocusIndicatorHost.vue"
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
  props: { ui_preferences: { focus_indicator_opacity: number } }
}>({
  component: "Schedule",
  props: { ui_preferences: { focus_indicator_opacity: 0.42 } },
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
const Publisher = defineComponent({
  props: { blocks: { type: Array as () => TimeBlock[], required: true } },
  setup(props) {
    controller = inject(FocusIndicatorControllerKey)!
    controller.publish("2026-08-12", props.blocks)
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
  page.props.ui_preferences.focus_indicator_opacity = 0.42
  nowMinutes.value = 570
  nowDate.value = "2026-08-12"
  controller = null
  clearFocusIndicatorShouldBeOpen()
})

afterEach(() => {
  delete (window as unknown as { documentPictureInPicture?: unknown }).documentPictureInPicture
  clearFocusIndicatorShouldBeOpen()
  vi.restoreAllMocks()
})

describe("FocusIndicatorHost", () => {
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

  it("opens the PiP at the account opacity present from the first mount", async () => {
    page.props.ui_preferences.focus_indicator_opacity = 0.33
    const win = makeFakeWindow()
    installFakePip(win)
    const wrapper = mount(FocusIndicatorHost, {
      slots: { default: () => h(Publisher, { blocks: [block()] }) },
    })
    await controller!.focusIndicator.open()
    await flushPromises()

    const root = win.document.querySelector(".fi-root") as HTMLElement
    expect(root.style.getPropertyValue("--focus-indicator-opacity")).toBe("0.33")
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
    expect(win.document.querySelector(".fi-neutral")?.textContent).toBe("—")
    wrapper.unmount()
  })

  it("updates opacity in the existing PiP when the reactive account preference changes", async () => {
    const win = makeFakeWindow()
    const requestWindow = installFakePip(win)
    const wrapper = mount(FocusIndicatorHost, { slots: { default: () => h(Publisher, { blocks: [block()] }) } })
    await controller!.focusIndicator.open()
    await flushPromises()
    const root = win.document.querySelector(".fi-root") as HTMLElement
    expect(root.style.getPropertyValue("--focus-indicator-opacity")).toBe("0.42")

    page.props.ui_preferences.focus_indicator_opacity = 0.68
    await nextTick()

    expect(root.style.getPropertyValue("--focus-indicator-opacity")).toBe("0.68")
    expect(requestWindow).toHaveBeenCalledTimes(1)
    expect(win.close).not.toHaveBeenCalled()
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
