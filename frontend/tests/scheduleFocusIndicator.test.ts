/**
 * Slice 6 integration: the focus indicator wired into Schedule.vue.
 *
 * Covers the wiring the piece-level unit tests can't: active-block derivation
 * from the live now-signal, the integration privacy gate over the REAL PiP
 * document (body + title), onComplete → shared controller, the just-completed
 * suppression, and disabled passthrough.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount, VueWrapper } from "@vue/test-utils"
import { nextTick, reactive, ref, type Ref } from "vue"

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
  return wrapper as unknown as { vm: any }
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
  vi.unstubAllGlobals()
})

function installFakePip(win: ReturnType<typeof makeFakeWindow>) {
  ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
    requestWindow: vi.fn().mockResolvedValue(win),
    window: null,
  }
}

describe("Schedule.vue focus indicator", () => {
  it("derives an active indicator from the current unfinished block", async () => {
    mountPage([makeBlock()])
    await flushPromises()
    expect((wrapper as unknown as { vm: { indicatorActive: boolean } }).vm.indicatorActive).toBe(true)
    // 09:30 of a 09:00–10:00 block = 50%
    expect((wrapper as unknown as { vm: { indicatorPercent: number } }).vm.indicatorPercent).toBe(50)
  })

  it("is neutral when the current block is completed", async () => {
    mountPage([makeBlock({ is_completed: true })])
    await flushPromises()
    expect((wrapper as unknown as { vm: { indicatorActive: boolean } }).vm.indicatorActive).toBe(false)
  })

  it("renders the ShowIndicatorButton in the header actions slot", async () => {
    installFakePip(makeFakeWindow()) // → supported=true, label "Show indicator"
    mountPage([makeBlock()])
    await flushPromises()
    expect(wrapper!.find(".show-indicator-btn").exists()).toBe(true)
    expect(wrapper!.text()).toContain("Show indicator")
  })

  it("leaks NO private block data into the real PiP document (body or title)", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    mountPage([makeBlock()])
    await flushPromises()
    await vm().vm.focusIndicator.open()
    await flushPromises()
    expect(win.document.querySelector('[role="progressbar"]')).not.toBeNull()
    const html = win.document.body.innerHTML
    for (const s of PRIVATE) expect(html).not.toContain(s)
    const headHtml = win.document.head.innerHTML
    for (const s of PRIVATE) expect(headHtml).not.toContain(s)
    expect(win.document.title).toBe("Focus")
    for (const s of PRIVATE) expect(win.document.title).not.toContain(s)
  })

  it("completing via the indicator calls the shared controller and folds the block to neutral", async () => {
    mountPage([makeBlock({ id: 42 })])
    await flushPromises()
    await vm().vm.handleIndicatorComplete()
    await flushPromises()
    expect(scheduleUpdateBlock).toHaveBeenCalledWith(
      42,
      { is_completed: true },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(vm().vm.justCompletedId).toBe(42)
    expect(vm().vm.indicatorActive).toBe(false)
  })

  it("passes the schedule-disabled state through to the indicator props", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    isGeneratingDraft.value = true // → scheduleDisabled
    mountPage([makeBlock()])
    await flushPromises()
    await vm().vm.focusIndicator.open()
    await flushPromises()
    const btn = win.document.querySelector("button.fi-complete") as HTMLButtonElement | null
    expect(btn).not.toBeNull()
    expect(btn!.disabled).toBe(true)
  })

  it("handleIndicatorComplete is a no-op when there is no active block", async () => {
    nowMinutes.value = 660 // past the 09:00–10:00 block → no active block
    mountPage([makeBlock()])
    await flushPromises()
    expect(vm().vm.indicatorActive).toBe(false)
    await vm().vm.handleIndicatorComplete()
    await flushPromises()
    expect(scheduleUpdateBlock).not.toHaveBeenCalled()
  })

  it("resets the controller when the active block identity changes mid-completion (C3)", async () => {
    let resolveUpdate: ((v: { ok: boolean }) => void) | null = null
    scheduleUpdateBlock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpdate = resolve
        }),
    )
    mountPage([makeBlock({ id: 5 })])
    await flushPromises()
    // Start a completion that stays in-flight.
    const p = vm().vm.handleIndicatorComplete()
    await flushPromises()
    expect(vm().vm.focusCompletion.saving.value).toBe(true)

    // Active identity changes mid-flight: advance the clock past the block's end
    // so rawActiveBlock becomes null → the reset watch fires.
    nowMinutes.value = 620
    await nextTick()
    await nextTick()
    expect(vm().vm.focusCompletion.saving.value).toBe(false)
    expect(vm().vm.focusCompletion.errorState.value).toBe(false)
    expect(vm().vm.indicatorActive).toBe(false)

    // The superseded chain resolves without touching state or pushing undo.
    resolveUpdate!({ ok: true })
    await p
    await flushPromises()
    expect(pushUndo).not.toHaveBeenCalled()
    expect(vm().vm.focusCompletion.saving.value).toBe(false)
  })

  it("re-activates the indicator when a completed block is undone (props.blocks update clears suppression)", async () => {
    mountPage([makeBlock({ id: 7 })])
    await flushPromises()
    await vm().vm.handleIndicatorComplete()
    await flushPromises()
    expect(vm().vm.justCompletedId).toBe(7)
    expect(vm().vm.indicatorActive).toBe(false)
    // Undo restore lands: props.blocks replaced (block still incomplete + current).
    await wrapper!.setProps({ blocks: [makeBlock({ id: 7, is_completed: false })] })
    await flushPromises()
    expect(vm().vm.justCompletedId).toBeNull()
    expect(vm().vm.indicatorActive).toBe(true)
  })
})
