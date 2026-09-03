/**
 * Slice 6 integration: the focus indicator wired into Schedule.vue.
 *
 * Covers the wiring the piece-level unit tests can't: active-block derivation
 * from the live now-signal, remaining-minutes countdown in the PiP body, and
 * the integration privacy gate over the REAL PiP document (body + title).
 * Completing a block stays on the timeline checkbox.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount, VueWrapper } from "@vue/test-utils"
import { reactive, ref, type Ref } from "vue"

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn(), visit: vi.fn(), post: vi.fn() },
  Link: { name: "Link", template: "<a><slot /></a>" },
  usePage: () => ({ props: {} }),
}))

const isGeneratingDraft = ref(false)
const lastDraftError: Ref<string | null> = ref(null)
vi.mock("../src/composables/useDraft", () => ({
  useDraft: () => ({
    isGeneratingDraft,
    lastDraftError,
    generateDraft: vi.fn().mockResolvedValue({ ok: true, explanation: null }),
    clearDraftError: vi.fn(),
    abandonInFlight: vi.fn(),
  }),
}))

const scheduleUpdateBlock = vi.fn().mockResolvedValue({ ok: true })
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    reorderBlocks: vi.fn(),
    createBlock: vi.fn(),
    updateBlock: scheduleUpdateBlock,
    deleteBlock: vi.fn(),
    restoreBlocks: vi.fn(),
  }),
}))

const pushUndo = vi.fn()
const snapshotBlocks = vi.fn(() => [])
vi.mock("../src/composables/useUndo", () => ({
  useUndo: () => ({
    undoStack: ref([]),
    canUndo: ref(false),
    currentToast: ref(null),
    pushUndo,
    performUndo: vi.fn(),
    snapshotBlocks,
    dismissToast: vi.fn(),
  }),
}))

// Controllable wall clock: today at 09:30, so a 09:00–10:00 block is current.
const nowMinutes = ref<number | null>(570)
const nowDate = ref<string | null>("2026-08-12")
vi.mock("../src/composables/useNowMinutes", () => ({
  useNowMinutes: () => ({ nowMinutes, nowDate }),
}))

vi.mock("../src/composables/useTravelRules", () => ({
  useTravelRules: () => ({
    listRules: vi.fn().mockResolvedValue({ ok: true, rules: [] }),
    createRule: vi.fn(),
    updateRule: vi.fn(),
    deleteRule: vi.fn(),
  }),
}))

vi.mock("../src/composables/useDrag", () => ({
  clampedDragDuration: () => 30,
  useDrag: () => ({
    isDragging: ref(false),
    dragBlockId: ref<number | null>(null),
    ghostTop: ref(0),
    previewStartTime: ref(""),
    previewEndTime: ref(""),
    previewBlocks: ref([]),
    shiftedBlockIds: ref(new Set<number>()),
    startDrag: vi.fn(),
    endDrag: vi.fn(),
    cancelDrag: vi.fn(),
  }),
}))

function makeProviderState() {
  return reactive({
    events: [] as unknown[],
    tasks: [] as unknown[],
    loading: false,
    error: null as string | null,
    connected: false,
    statusKnown: false,
    accountErrors: [] as unknown[],
  })
}
const calendarState = makeProviderState()
const googleCalendarState = makeProviderState()
const todoistState = makeProviderState()
const habiticaState = makeProviderState()

vi.mock("../src/composables/useCalendar", () => ({
  useCalendar: () => ({ state: calendarState, fetchEvents: vi.fn(), refreshEvents: vi.fn(), fetchAccountStatus: vi.fn() }),
}))
vi.mock("../src/composables/useGoogleCalendar", () => ({
  useGoogleCalendar: () => ({ state: googleCalendarState, fetchEvents: vi.fn(), refreshEvents: vi.fn(), fetchAccountStatus: vi.fn() }),
}))
vi.mock("../src/composables/useTodoist", () => ({
  useTodoist: () => ({ state: todoistState, fetchTasks: vi.fn(), refreshTasks: vi.fn(), completeTask: vi.fn(), fetchAccountStatus: vi.fn() }),
}))
vi.mock("../src/composables/useHabitica", () => ({
  useHabitica: () => ({ state: habiticaState, fetchTasks: vi.fn(), refreshTasks: vi.fn(), completeTask: vi.fn(), fetchAccountStatus: vi.fn() }),
}))
vi.mock("../src/composables/useExternalSourcePoll", () => ({
  useExternalSourcePoll: () => {},
}))

import Schedule from "../src/pages/Schedule.vue"
import type { Schedule as ScheduleType, TimeBlock } from "../src/types"
import {
  clearFocusIndicatorShouldBeOpen,
  readFocusIndicatorShouldBeOpen,
} from "../src/utils/focusIndicatorStorage"

const PRIVATE = ["Standup with Bob", "work", "2026-08-12", "09:00", "10:00"]

function makeBlock(overrides: Partial<TimeBlock> = {}): TimeBlock {
  return {
    id: 1,
    title: "Standup with Bob",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
    ...overrides,
  }
}

const STUBS = {
  DateNavigator: { template: "<div><slot name='status' /><slot name='actions' /></div>" },
  TimeBlock: true,
  GapSlot: true,
  AddBlockForm: true,
  NowLine: true,
  UndoToast: true,
  CommandBar: true,
  ChatSidebar: true,
  DraftBadge: true,
  RegenerateDraftButton: true,
}

function makeFakeWindow() {
  const doc = document.implementation.createHTMLDocument("")
  const listeners: Record<string, Array<() => void>> = {}
  return {
    document: doc,
    closed: false,
    addEventListener: (t: string, h: () => void) => {
      ;(listeners[t] ||= []).push(h)
    },
    removeEventListener: (t: string, h: () => void) => {
      listeners[t] = (listeners[t] || []).filter((x) => x !== h)
    },
    close: vi.fn(),
    _emit: (t: string) => (listeners[t] || []).forEach((h) => h()),
  }
}

function stubMatchMedia(): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  )
}

let wrapper: VueWrapper | null = null

function mountPage(blocks: TimeBlock[], date = "2026-08-12") {
  wrapper = mount(Schedule, {
    props: {
      schedule: { id: 1, date, status: "active" } as ScheduleType,
      blocks,
      date,
      auto_draft_pending: false,
      has_template_for_type: true,
      slot_type: "weekday" as const,
    },
    global: { stubs: STUBS },
  })
  return wrapper
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function vm(): any {
  return (wrapper as unknown as { vm: any }).vm
}

beforeEach(() => {
  stubMatchMedia()
  nowMinutes.value = 570
  nowDate.value = "2026-08-12"
  isGeneratingDraft.value = false
  scheduleUpdateBlock.mockClear().mockResolvedValue({ ok: true })
  pushUndo.mockClear()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  delete (window as unknown as { documentPictureInPicture?: unknown }).documentPictureInPicture
  clearFocusIndicatorShouldBeOpen()
  vi.unstubAllGlobals()
})

function installFakePip(win: ReturnType<typeof makeFakeWindow>) {
  const requestWindow = vi.fn().mockResolvedValue(win)
  ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
    requestWindow,
    window: null,
  }
  return requestWindow
}

describe("Schedule.vue focus indicator", () => {
  it("derives an active indicator from the current unfinished block", async () => {
    mountPage([makeBlock()])
    await flushPromises()
    expect(vm().indicatorActive).toBe(true)
    // 09:30 of a 09:00–10:00 block = 50%
    expect(vm().indicatorPercent).toBe(50)
  })

  it("is neutral when the current block is completed", async () => {
    mountPage([makeBlock({ is_completed: true })])
    await flushPromises()
    expect(vm().indicatorActive).toBe(false)
  })

  it("renders the ShowIndicatorButton in the header actions slot", async () => {
    installFakePip(makeFakeWindow()) // → supported=true, label "Show indicator"
    mountPage([makeBlock()])
    await flushPromises()
    expect(wrapper!.find(".show-indicator-btn").exists()).toBe(true)
    expect(wrapper!.text()).toContain("Show indicator")
  })

  it("Hide explicitly closes and clears intent, then Show opens again", async () => {
    const win = makeFakeWindow()
    const requestWindow = installFakePip(win)
    mountPage([makeBlock()])
    await wrapper!.get(".show-indicator-btn").trigger("click")
    await flushPromises()
    expect(wrapper!.text()).toContain("Hide indicator")
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)

    await wrapper!.get(".show-indicator-btn").trigger("click")
    await flushPromises()
    expect(win.close).toHaveBeenCalledTimes(1)
    expect(readFocusIndicatorShouldBeOpen()).toBe(false)
    expect(wrapper!.text()).toContain("Show indicator")

    await wrapper!.get(".show-indicator-btn").trigger("click")
    await flushPromises()
    expect(requestWindow).toHaveBeenCalledTimes(2)
    expect(wrapper!.text()).toContain("Hide indicator")
  })

  it("the in-PiP close control returns the schedule header to Show", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    mountPage([makeBlock()])
    await wrapper!.get(".show-indicator-btn").trigger("click")
    await flushPromises()
    expect(wrapper!.text()).toContain("Hide indicator")

    ;(win.document.querySelector(".fi-close") as HTMLButtonElement).click()
    await flushPromises()

    expect(win.close).toHaveBeenCalledTimes(1)
    expect(wrapper!.text()).toContain("Show indicator")
  })

  it("browser PiP pagehide (Back to tab) preserves restore intent and returns the header to Show", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    mountPage([makeBlock()])
    await wrapper!.get(".show-indicator-btn").trigger("click")
    await flushPromises()
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)

    win._emit("pagehide")
    await flushPromises()

    // Chrome closed the window, but it stays restorable — intent preserved,
    // header back to Show so one click reopens it.
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)
    expect(wrapper!.text()).toContain("Show indicator")
  })

  it("surfaces a PiP open failure beside the header control", async () => {
    ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
      requestWindow: vi.fn().mockRejectedValue(
        new DOMException("User activation is required", "NotAllowedError"),
      ),
      window: null,
    }
    mountPage([makeBlock()])
    await flushPromises()

    await wrapper!.get(".show-indicator-btn").trigger("click")
    await flushPromises()

    expect(wrapper!.get('[role="alert"]').text()).toBe(
      "Could not open indicator. Please try again.",
    )
  })

  it("leaks NO private block data into the real PiP document (body or title)", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    mountPage([makeBlock()])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).not.toBeNull()
    const html = win.document.body.innerHTML
    // Derived countdown is allowed; clock times / title / category / date are not.
    expect(win.document.body.textContent).toContain("30m left")
    for (const s of PRIVATE) expect(html).not.toContain(s)
    const headHtml = win.document.head.innerHTML
    for (const s of PRIVATE) expect(headHtml).not.toContain(s)
    expect(win.document.title).toBe("Focus")
    for (const s of PRIVATE) expect(win.document.title).not.toContain(s)
  })

  it("is inactive for a completed current block and re-activates when that block is restored incomplete", async () => {
    mountPage([makeBlock({ id: 7, is_completed: true })])
    await flushPromises()
    expect(vm().indicatorActive).toBe(false)
    await wrapper!.setProps({ blocks: [makeBlock({ id: 7, is_completed: false })] })
    await flushPromises()
    expect(vm().indicatorActive).toBe(true)
  })

  it("bridges an idle gap to PiP with the nearest future title and live countdown", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 600
    mountPage([
      makeBlock({ id: 2, title: "Deep focus", start_time: "11:00", end_time: "12:00" }),
      makeBlock({ id: 3, title: "Unrelated private plan", start_time: "12:00", end_time: "13:00" }),
    ])
    await flushPromises()
    expect(vm().indicatorActive).toBe(false)
    expect(vm().indicatorNextBlockTitle).toBe("Deep focus")
    expect(vm().indicatorNextBlockRemaining).toBe(60)
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.body.textContent).toContain("Deep focus")
    expect(win.document.body.textContent).toContain("1h left")
    expect(win.document.body.textContent).not.toContain("Unrelated private plan")
    expect(win.document.body.textContent).not.toContain("2026-08-12")
    expect(win.document.body.textContent).not.toContain("11:00")
    expect(win.document.title).toBe("Focus")
    expect(win.document.querySelector('[role="progressbar"]')).toBeNull()

    nowMinutes.value = 630
    await flushPromises()
    expect(win.document.body.textContent).toContain("30m left")
  })

  it("replaces an open active bar with next-block details when the clock enters a gap", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    mountPage([
      makeBlock({ id: 1, title: "Standup with Bob" }),
      makeBlock({ id: 2, title: "Deep work", start_time: "11:00", end_time: "12:00" }),
    ])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).not.toBeNull()

    nowMinutes.value = 600
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).toBeNull()
    expect(win.document.body.textContent).toContain("Deep work")
    expect(win.document.body.textContent).toContain("1h left")
  })

  it("keeps active PiP state title-free even when a later block exists", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    mountPage([
      makeBlock({ id: 1, title: "Standup with Bob" }),
      makeBlock({ id: 2, title: "Deep work", start_time: "11:00", end_time: "12:00" }),
    ])
    await flushPromises()
    expect(vm().indicatorNextBlock).toBeNull()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).not.toBeNull()
    expect(win.document.body.textContent).not.toContain("Standup with Bob")
    expect(win.document.body.textContent).not.toContain("Deep work")
  })

  it("shows a completed future block's real title (not Untitled)", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 600
    mountPage([
      makeBlock({ id: 1, title: "Dentist", start_time: "11:00", end_time: "12:00", is_completed: true }),
    ])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.body.textContent).toContain("Dentist")
    expect(win.document.body.textContent).toContain("1h left")
    expect(win.document.body.textContent).not.toContain("Untitled")
  })

  it("uses Untitled for an empty-title future block", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 600
    mountPage([
      makeBlock({ id: 1, title: "", start_time: "11:00", end_time: "12:00" }),
    ])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.body.textContent).toContain("Untitled")
    expect(win.document.body.textContent).toContain("1h left")
  })

  it("uses Untitled for a whitespace-only-title future block", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 600
    mountPage([
      makeBlock({ id: 1, title: "   ", start_time: "11:00", end_time: "12:00" }),
    ])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.body.textContent).toContain("Untitled")
    expect(win.document.body.textContent).toContain("1h left")
  })

  it("selects the nearest later block when now sits inside a completed block", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 570 // 09:30, inside the 09:00–10:00 completed block
    mountPage([
      makeBlock({ id: 1, title: "Morning routine", start_time: "09:00", end_time: "10:00", is_completed: true }),
      makeBlock({ id: 2, title: "Deep work", start_time: "11:00", end_time: "12:00" }),
    ])
    await flushPromises()
    expect(vm().indicatorActive).toBe(false)
    expect(vm().indicatorNextBlockTitle).toBe("Deep work")
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).toBeNull()
    expect(win.document.body.textContent).toContain("Deep work")
    expect(win.document.body.textContent).not.toContain("Morning routine")
  })

  it("keeps PiP neutral when no block starts after now", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 800 // 13:20, after the only block has ended
    mountPage([makeBlock({ title: "Deep work", start_time: "11:00", end_time: "12:00" })])
    await flushPromises()
    expect(vm().indicatorNextBlock).toBeNull()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector(".fi-neutral")?.textContent).toBe("—")
    expect(win.document.body.textContent).toContain("No active block")
    expect(win.document.body.textContent).not.toContain("Deep work")
  })

  it("keeps PiP neutral off-today even with a later-looking block and finite now", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 600 // finite minute…
    nowDate.value = null // …but the today-signal is off (viewing another day)
    mountPage([makeBlock({ title: "Deep work", start_time: "11:00", end_time: "12:00" })])
    await flushPromises()
    expect(vm().indicatorNextBlock).toBeNull()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector(".fi-neutral")?.textContent).toBe("—")
    expect(win.document.body.textContent).toContain("No active block")
    expect(win.document.body.textContent).not.toContain("Deep work")
  })

  it.each([
    ["unparseable start", 600, "bad", "12:00"],
    ["unparseable end", 600, "11:00", "bad"],
    ["zero duration", 600, "11:00", "11:00"],
    ["negative duration", 600, "11:00", "10:00"],
  ])("keeps PiP neutral for %s next-block data", async (_name, minute, start_time, end_time) => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = minute as number
    mountPage([makeBlock({ title: "Deep work", start_time, end_time })])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector(".fi-neutral")?.textContent).toBe("—")
    expect(win.document.body.textContent).toContain("No active block")
    expect(win.document.body.textContent).not.toContain("Deep work")
  })

  it("replaces next-block details with a private active state when the clock reaches its start", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 600
    mountPage([makeBlock({ title: "Deep work", start_time: "11:00", end_time: "12:00" })])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.body.textContent).toContain("Deep work")

    nowMinutes.value = 660
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).not.toBeNull()
    expect(win.document.body.textContent).toContain("1h left")
    expect(win.document.body.textContent).not.toContain("Deep work")
  })

  it("updates an open gap indicator when effective blocks change", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    nowMinutes.value = 600
    mountPage([makeBlock({ id: 2, title: "Later", start_time: "12:00", end_time: "13:00" })])
    await flushPromises()
    await vm().focusIndicator.open()
    await flushPromises()
    expect(win.document.body.textContent).toContain("Later")

    await wrapper!.setProps({
      blocks: [makeBlock({ id: 3, title: "Sooner", start_time: "11:00", end_time: "12:00" })],
    })
    await flushPromises()
    expect(win.document.body.textContent).toContain("Sooner")
    expect(win.document.body.textContent).toContain("1h left")
    expect(win.document.body.textContent).not.toContain("Later")
  })
})
