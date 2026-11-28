import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { defineComponent, h, nextTick, ref } from "vue"
import { ScheduleUndoKey } from "../src/composables/scheduleContext"
import { makeCategories } from "./helpers/schedule"

const mockCreateBlock = vi.fn()
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({ createBlock: mockCreateBlock }),
}))

import AddBlockForm from "../src/components/AddBlockForm.vue"
import BottomSheet from "../src/components/BottomSheet.vue"
import MobileFab from "../src/components/MobileFab.vue"
import { useBodyScrollLock } from "../src/composables/useBodyScrollLock"
import { useVisualViewportInset } from "../src/composables/useVisualViewportInset"

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.clearAllMocks()
  document.documentElement.style.overflow = ""
  document.body.style.overflow = ""
})

function mountForm(props: Record<string, unknown>) {
  return mount(AddBlockForm, {
    props: { date: "2026-11-27", categories: makeCategories(), ...props },
    attachTo: document.body,
    global: { provide: { [ScheduleUndoKey]: { pushUndo: vi.fn() } } },
  })
}

describe("AddBlockForm on the phone (feature 0113)", () => {
  it("renders no Add Block bar and no sheet until asked", () => {
    const w = mountForm({ mobile: true })
    expect(w.find(".add-btn").exists()).toBe(false)
    expect(document.body.querySelector('[data-testid="bottom-sheet"]')).toBeNull()
  })

  it("opens the form in a sheet for a request with a range, prefilled", async () => {
    const w = mountForm({ mobile: true, initialStartTime: "14:20", initialEndTime: "16:05" })
    await w.setProps({ addRequestId: 1 })
    const sheet = document.body.querySelector('[data-testid="bottom-sheet"]')
    expect(sheet).not.toBeNull()
    expect(sheet?.getAttribute("role")).toBe("dialog")
    const times = Array.from(sheet!.querySelectorAll<HTMLInputElement>('input[type="time"]')).map((el) => el.value)
    expect(times).toEqual(["14:20", "16:05"])
  })

  it("opens the same defaults as the bar for a FAB request with no range", async () => {
    const w = mountForm({ mobile: true, initialStartTime: "14:20", initialEndTime: "16:05" })
    await w.setProps({ addRequestId: 1 })
    await w.setProps({ initialStartTime: undefined, initialEndTime: undefined, addRequestId: 2 })
    const times = Array.from(document.body.querySelectorAll<HTMLInputElement>('[data-testid="bottom-sheet"] input[type="time"]')).map((el) => el.value)
    expect(times).toEqual(["09:00", "10:00"])
  })

  it("closes the sheet on Cancel and on the Close button", async () => {
    const w = mountForm({ mobile: true })
    await w.setProps({ addRequestId: 1 })
    document.body.querySelector<HTMLButtonElement>(".cancel-btn")!.click()
    await nextTick()
    expect(document.body.querySelector('[data-testid="bottom-sheet"]')).toBeNull()
    await w.setProps({ addRequestId: 2 })
    document.body.querySelector<HTMLButtonElement>('[data-testid="sheet-close"]')!.click()
    await nextTick()
    expect(document.body.querySelector('[data-testid="bottom-sheet"]')).toBeNull()
  })

  it("leaves the desktop bar and inline form untouched", async () => {
    const w = mountForm({})
    expect(w.find(".add-btn").exists()).toBe(true)
    await w.get(".add-btn").trigger("click")
    expect(w.find(".add-form").exists()).toBe(true)
    expect(document.body.querySelector('[data-testid="bottom-sheet"]')).toBeNull()
  })
})

describe("MobileFab (feature 0113)", () => {
  it("is a labelled button that emits click, and honours disabled", async () => {
    const w = mount(MobileFab)
    expect(w.get("button").attributes("aria-label")).toBe("Add block")
    await w.get("button").trigger("click")
    expect(w.emitted("click")).toHaveLength(1)
    await w.setProps({ disabled: true })
    expect(w.get("button").attributes("disabled")).toBeDefined()
  })
})

describe("BottomSheet and scroll lock (feature 0113)", () => {
  const Host = defineComponent({
    props: { open: Boolean },
    emits: ["close"],
    setup(props, { emit }) {
      return () => props.open
        ? h(BottomSheet, { title: "Demo", onClose: () => emit("close") }, () => h("button", { "data-testid": "inside" }, "Inside"))
        : h("div")
    },
  })

  it("locks page scroll while open and restores the prior values", async () => {
    document.body.style.overflow = "scroll"
    const w = mount(Host, { props: { open: false }, attachTo: document.body })
    await w.setProps({ open: true })
    expect(document.documentElement.style.overflow).toBe("hidden")
    expect(document.body.style.overflow).toBe("hidden")
    await w.setProps({ open: false })
    expect(document.documentElement.style.overflow).toBe("")
    expect(document.body.style.overflow).toBe("scroll")
  })

  it("keeps the lock until the last of two overlapping locks is released", async () => {
    const Lock = defineComponent({ setup() { useBodyScrollLock(); return () => h("i") } })
    const a = mount(Lock)
    const b = mount(Lock)
    a.unmount()
    expect(document.body.style.overflow).toBe("hidden")
    b.unmount()
    expect(document.body.style.overflow).toBe("")
  })

  it("labels the dialog by its title, focuses in, closes on Escape and backdrop", async () => {
    const w = mount(Host, { props: { open: true }, attachTo: document.body })
    const sheet = document.body.querySelector('[data-testid="bottom-sheet"]') as HTMLElement
    const heading = document.getElementById(sheet.getAttribute("aria-labelledby")!)
    expect(heading?.textContent).toBe("Demo")
    expect(sheet.contains(document.activeElement)).toBe(true)
    sheet.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    expect(w.emitted("close")).toHaveLength(1)
    document.body.querySelector<HTMLElement>('[data-testid="sheet-backdrop"]')!.click()
    expect(w.emitted("close")).toHaveLength(2)
  })

  it("lifts the sheet above the keyboard by the visual viewport inset", async () => {
    const listeners: Record<string, () => void> = {}
    const vv = {
      height: 400, offsetTop: 0,
      addEventListener: (type: string, fn: () => void) => { listeners[type] = fn },
      removeEventListener: vi.fn(),
    }
    Object.defineProperty(window, "visualViewport", { value: vv, configurable: true })
    const insetRef = ref(0)
    const Probe = defineComponent({
      setup() { const inset = useVisualViewportInset(); insetRef.value = 0; return () => h("i", String(inset.value)) },
    })
    const w = mount(Probe, { attachTo: document.body })
    await nextTick()
    const expected = Math.max(0, Math.round(window.innerHeight - 400))
    expect(w.text()).toBe(String(expected))
    vv.height = window.innerHeight
    listeners.resize()
    await nextTick()
    expect(w.text()).toBe("0")
    Reflect.deleteProperty(window, "visualViewport")
    await flushPromises()
  })
})
