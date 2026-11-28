/**
 * Schedule.vue auto-draft watcher tests.
 *
 * The watcher in Schedule.vue must fire ``generateDraft`` exactly once
 * per ``(component instance, date)`` pair when the server reports
 * ``auto_draft_pending=true`` and the schedule is empty. This is the
 * load-bearing piece for the "draft auto-fires on a brand-new day"
 * UX — the same set of guards has to survive Inertia's partial reloads
 * (which DO NOT remount the component) and date navigation.
 *
 * Plan reference: 0005_PLAN.md "Test Coverage To Add → Frontend":
 *   (a) first mount with auto_draft_pending=true → fires once
 *   (b) navigating from May 3 → May 4 with same instance → fires twice
 *   (c) partial reload after success doesn't refire for the same date
 *   (d) restore_blocks with empty list (post-undo) doesn't refire
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { mount, VueWrapper, flushPromises } from "@vue/test-utils"
import { runScheduleMutation, type ScheduleRevisionState } from "../src/composables/useScheduleRevision"
import { makeCategories } from "./helpers/schedule"
import { router } from "@inertiajs/vue3"
import { defineComponent, h, nextTick, reactive, ref, type Ref } from "vue"

// --- mocks ---------------------------------------------------------------

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn(), visit: vi.fn(), post: vi.fn() },
  Link: { name: "Link", template: "<a><slot /></a>" },
  usePage: () => ({ props: {} }),
}))

const generateDraft = vi.fn()
// Default: succeed with no explanation so runDraft pushes a "draft" undo.
generateDraft.mockResolvedValue({ ok: true, explanation: null })

const abandonInFlight = vi.fn()

const isGeneratingDraft = ref(false)
const lastDraftError: Ref<string | null> = ref(null)
let revisionOwner: ScheduleRevisionState

vi.mock("../src/composables/useDraft", () => ({
  useDraft: (owner: ScheduleRevisionState) => {
    revisionOwner = owner
    return {
    isGeneratingDraft,
    lastDraftError,
    generateDraft,
    clearDraftError: vi.fn(),
    abandonInFlight,
  }
  },
}))

const { createBlockSpy } = vi.hoisted(() => ({ createBlockSpy: vi.fn() }))

vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    reorderBlocks: vi.fn(),
    createBlock: createBlockSpy,
    updateBlock: vi.fn(),
    deleteBlock: vi.fn(),
    restoreBlocks: vi.fn(),
  }),
}))

const pushUndo = vi.fn()
const snapshotBlocks = vi.fn(() => [])
const dismissToast = vi.fn()
const canUndo = ref(false)
const performUndo = vi.fn()

vi.mock("../src/composables/useUndo", () => ({
  useUndo: () => ({
    undoStack: ref([]),
    canUndo,
    currentToast: ref(null),
    pushUndo,
    performUndo,
    snapshotBlocks,
    dismissToast,
  }),
}))

// Schedule.vue fetches travel rules on setup (feature 0026). Without this the
// real composable issues a fetch during every mount in this file.
const listRules = vi.fn().mockResolvedValue({ ok: true, rules: [] })
const { matchTravelRule } = vi.hoisted(() => ({
  matchTravelRule: vi.fn(),
}))

vi.mock("../src/composables/useTravelRules", () => ({
  useTravelRules: () => ({
    listRules,
    createRule: vi.fn(),
    updateRule: vi.fn(),
    deleteRule: vi.fn(),
  }),
}))

vi.mock("../src/utils/travelRules", () => ({ matchTravelRule }))

const dragIsDragging = ref(false)
const dragBlockId = ref<number | null>(null)
const dragPreviewStart = ref("")
const dragPreviewEnd = ref("")
const cancelDrag = vi.fn(() => { dragIsDragging.value = false })
vi.mock("../src/composables/useDrag", () => ({
  // Schedule.vue imports this named helper for its drag-ghost geometry; a
  // factory omitting it leaves the binding undefined and throws when a ghost
  // renders.
  clampedDragDuration: (b: { start_time: string; end_time: string }) => {
    const minutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5))
    return Math.max(5, minutes(b.end_time) - minutes(b.start_time))
  },
  useDrag: () => ({
    frozenRenderBounds: ref(null),
    frozenNowMinutes: ref(null),
    frozenPxPerMinute: ref(2),
    frozenTimelineOriginMinutes: ref(null),
    frozenWindow: ref(null),
    isDragging: dragIsDragging,
    dragBlockId,
    ghostTop: ref(0),
    previewStartTime: dragPreviewStart,
    previewEndTime: dragPreviewEnd,
    previewBlocks: ref([]),
    shiftedBlockIds: ref(new Set<number>()),
    startDrag: vi.fn(),
    endDrag: vi.fn(),
    cancelDrag,
  }),
}))

// Controllable external-source mocks (feature 0031). Defaults keep panels
// hidden so existing auto-draft / chat-routing tests stay unchanged.
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

function integrationBootstrap(date: string, zone: string) {
  return {
    snapshot_id: `test:${date}:${zone}`, user_id: 1, date, time_zone: zone,
    connected: {
      apple: calendarState.connected, google: googleCalendarState.connected,
      todoist: todoistState.connected, habitica: habiticaState.connected,
    },
    travel_rules: [],
  }
}

const calendarRefreshEvents = vi.fn()
const googleCalendarRefreshEvents = vi.fn()
const todoistRefreshTasks = vi.fn()
const habiticaRefreshTasks = vi.fn()

function resetExternalProviderMocks(): void {
  for (const state of [
    calendarState,
    googleCalendarState,
    todoistState,
    habiticaState,
  ]) {
    state.events = []
    state.tasks = []
    state.loading = false
    state.error = null
    state.connected = false
    state.statusKnown = false
    state.accountErrors = []
  }
  calendarRefreshEvents.mockClear()
  googleCalendarRefreshEvents.mockClear()
  todoistRefreshTasks.mockClear()
  habiticaRefreshTasks.mockClear()
  capturedPollOptions = null
}

vi.mock("../src/composables/useCalendar", () => ({
  useCalendar: () => ({
    state: calendarState,
    invalidateAccount: (account = "disconnected") => { calendarState.connected = account === "connected"; calendarState.statusKnown = true },
    fetchEvents: vi.fn(),
    refreshEvents: calendarRefreshEvents,
    fetchAccountStatus: vi.fn(),
  }),
}))

vi.mock("../src/composables/useGoogleCalendar", () => ({
  useGoogleCalendar: () => ({
    state: googleCalendarState,
    invalidateAccount: (account = "disconnected") => { googleCalendarState.connected = account === "connected"; googleCalendarState.statusKnown = true },
    fetchEvents: vi.fn(),
    refreshEvents: googleCalendarRefreshEvents,
    fetchAccountStatus: vi.fn(),
  }),
}))

vi.mock("../src/composables/useTodoist", () => ({
  useTodoist: () => ({
    state: todoistState,
    invalidateAccount: (account = "disconnected") => { todoistState.connected = account === "connected"; todoistState.statusKnown = true },
    fetchTasks: vi.fn(),
    refreshTasks: todoistRefreshTasks,
    completeTask: vi.fn(),
    fetchAccountStatus: vi.fn(),
  }),
}))

vi.mock("../src/composables/useHabitica", () => ({
  useHabitica: () => ({
    state: habiticaState,
    invalidateAccount: (account = "disconnected") => { habiticaState.connected = account === "connected"; habiticaState.statusKnown = true },
    fetchTasks: vi.fn(),
    refreshTasks: habiticaRefreshTasks,
    completeTask: vi.fn(),
    fetchAccountStatus: vi.fn(),
  }),
}))

type CapturedPollOptions = {
  intervalSeconds: { value: number }
  date: { value: string }
  active: { value: boolean }
  refresh: (date: string) => void | Promise<void>
}

let capturedPollOptions: CapturedPollOptions | null = null

vi.mock("../src/composables/useExternalSourcePoll", () => ({
  useExternalSourcePoll: (opts: CapturedPollOptions) => {
    capturedPollOptions = opts
  },
}))

// Import AFTER all mocks so the SUT picks them up.
import Schedule from "../src/pages/Schedule.vue"
import ExternalEventsPanel from "../src/components/ExternalEventsPanel.vue"
import type { Schedule as ScheduleType, TimeBlock, UserCategory } from "../src/types"
import { useExternalCalendarPlacement } from "../src/composables/useExternalCalendarPlacement"
import { EXTERNAL_TASKS_SIDEBAR_OPEN_KEY } from "../src/utils/externalTasksSidebarStorage"
import { todayString } from "../src/utils/date"

// --- helpers -------------------------------------------------------------

function makeSchedule(date: string, status: ScheduleType["status"] = "draft"): ScheduleType {
  return { id: 1, date, status, revision: 0 }
}

function makeBlock(id: number): TimeBlock {
  return {
    id,
    title: `Block ${id}`,
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: id,
  }
}

const STUBS = {
  // The page's ``displayList`` computed walks ``blocks`` to render
  // children — stubbing keeps the unit test focused on the watcher.
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

// JSDOM doesn't ship matchMedia; useViewport() (called on Schedule mount
// since feature 0008) needs a stub. Default to narrow (matches=false)
// for the auto-draft tests — they don't care about the chat surface.
function stubMatchMedia(matches = false): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      // `matches` stands for the wide query; the mobile query (feature 0113)
      // is false unless a test stubs it itself.
      matches: query.includes("max-width") ? false : matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })),
  )
}

function stubLocalStorage(): void {
  const store: Record<string, string> = {}
  vi.stubGlobal("localStorage", {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = String(value)
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key]
    }),
    clear: vi.fn(() => {
      for (const key of Object.keys(store)) delete store[key]
    }),
    key: vi.fn((index: number) => Object.keys(store)[index] ?? null),
    get length() {
      return Object.keys(store).length
    },
  })
}

let wrapper: VueWrapper | null = null

function mountPage(props: {
  schedule: ScheduleType
  blocks: TimeBlock[]
  date: string
  categories?: UserCategory[]
  auto_draft_pending?: boolean
  has_template_for_type?: boolean
  slot_type?: "weekday" | "weekend"
  schedule_window?: { start: string; end: string; time_zone: string }
}) {
  wrapper = mount(Schedule, {
    props: {
      categories: makeCategories(),
      auto_draft_pending: false,
      has_template_for_type: true,
      slot_type: "weekday" as const,
      schedule_window: { start: "06:00", end: "23:00", time_zone: "Asia/Almaty" },
      auth_user_id: 1,
      integration_bootstrap: integrationBootstrap(props.date, props.schedule_window?.time_zone ?? "Asia/Almaty"),
      ...props,
    },
    global: { stubs: STUBS },
  })
  return wrapper
}

describe("Schedule.vue auto-draft watcher", () => {
  beforeEach(() => {
    canUndo.value = false
    dragIsDragging.value = false
    dragBlockId.value = null
    cancelDrag.mockClear()
    stubLocalStorage()
    stubMatchMedia(false)
    resetExternalProviderMocks()
    generateDraft.mockResolvedValue({ ok: true, explanation: null })
    isGeneratingDraft.value = false
    lastDraftError.value = null
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it("passes the persisted schedule timezone to the page-level mismatch prompt", () => {
    const page = mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
    })
    expect(page.findComponent({ name: "TimeZoneMismatchPrompt" }).props("timeZone")).toBe("Asia/Almaty")
  })

  it("offers button Undo for silent mutations without requiring a keyboard", async () => {
    const page = mountPage({
      schedule: makeSchedule("2026-05-04"), blocks: [], date: "2026-05-04",
    })
    const button = page.get('[aria-label="Undo last change"]')
    expect(button.attributes("disabled")).toBeDefined()
    canUndo.value = true
    await nextTick()
    expect(button.attributes("disabled")).toBeUndefined()
    await button.trigger("click")
    expect(performUndo).toHaveBeenCalledOnce()
    canUndo.value = false
    await nextTick()
    expect(button.attributes("disabled")).toBeDefined()
  })

  it("disables button Undo while another schedule write is in flight", async () => {
    const date = "2026-05-04"
    const page = mountPage({ schedule: makeSchedule(date), blocks: [], date })
    canUndo.value = true
    await nextTick()
    let finish!: () => void
    const waiting = new Promise<void>((resolve) => { finish = resolve })
    const pending = runScheduleMutation(revisionOwner, date, async () => {
      await waiting
      return { ok: true, data: {
        revision: 1, schedule: { ...makeSchedule(date), revision: 1 }, blocks: [],
      } }
    })
    await nextTick()
    const button = page.get('[aria-label="Undo last change"]')
    expect(button.attributes("disabled")).toBeDefined()
    await button.trigger("click")
    expect(performUndo).not.toHaveBeenCalled()
    finish()
    await pending
    await nextTick()
    expect(button.attributes("disabled")).toBeUndefined()
  })

  it("shows a reload error instead of schedule controls for an empty catalog", () => {
    const page = mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      categories: [],
      auto_draft_pending: true,
    })
    expect(page.get('[role="alert"]').text()).toContain("Category data could not be loaded")
    expect(page.find(".add-btn").exists()).toBe(false)
    expect(generateDraft).not.toHaveBeenCalled()
  })

  it("cancels an active drag when a partial reload corrupts the catalog", async () => {
    const page = mountPage({
      schedule: makeSchedule("2026-05-04"), blocks: [], date: "2026-05-04",
    })
    dragIsDragging.value = true
    await page.setProps({ categories: [] })
    expect(cancelDrag).toHaveBeenCalledOnce()
    expect(dragIsDragging.value).toBe(false)
    expect(page.get('[role="alert"]').text()).toContain("Category data could not be loaded")
  })

  it.each([
    ["short", "09:00", "09:15", "15m"],
    ["long", "09:00", "10:30", "1h 30m"],
  ])("renders the drag ghost of a %s block as one row", async (_label, start, end, duration) => {
    const block = { ...makeBlock(7), start_time: start, end_time: end }
    const page = mountPage({
      schedule: makeSchedule("2026-05-04"), blocks: [block], date: "2026-05-04",
    })
    dragBlockId.value = 7
    dragPreviewStart.value = "11:00"
    dragPreviewEnd.value = "11:45"
    dragIsDragging.value = true
    await nextTick()

    const ghost = page.get(".drag-ghost")
    expect(ghost.findAll('input[type="checkbox"]')).toHaveLength(1)
    expect(ghost.get(".ghost-time").text()).toBe("11:00–11:45")
    expect(ghost.get(".ghost-duration").text()).toBe(duration)
    expect(ghost.get(".ghost-title").text()).toBe("Block 7")
    expect(ghost.find(".ghost-header").exists()).toBe(false)
    expect(ghost.classes()).not.toContain("compact")
  })

  it("(a) fires generateDraft once on first mount when auto_draft_pending=true and blocks are empty", async () => {
    mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)
    expect(generateDraft).toHaveBeenCalledWith("2026-05-04", pushUndo)
  })

  it("does NOT fire when auto_draft_pending=false on mount", async () => {
    mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: false,
    })
    await flushPromises()
    expect(generateDraft).not.toHaveBeenCalled()
  })

  it("does NOT fire when blocks are non-empty even with auto_draft_pending=true", async () => {
    mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [makeBlock(1)],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(generateDraft).not.toHaveBeenCalled()
  })

  it("(b) fires for each new date when navigating with the same component instance", async () => {
    const w = mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)
    expect(generateDraft).toHaveBeenLastCalledWith("2026-05-04", pushUndo)

    // Inertia partial reload to a new date — same component instance.
    await w.setProps({
      schedule: makeSchedule("2026-05-05"),
      blocks: [],
      date: "2026-05-05",
      auto_draft_pending: true,
      has_template_for_type: true,
      slot_type: "weekday",
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(2)
    expect(generateDraft).toHaveBeenLastCalledWith("2026-05-05", pushUndo)
  })

  it("(c) does NOT refire after a partial reload populates blocks then clears them on the same date", async () => {
    const w = mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)

    // Server applied draft → partial reload pushes blocks.
    await w.setProps({
      schedule: makeSchedule("2026-05-04"),
      blocks: [makeBlock(1)],
      date: "2026-05-04",
      auto_draft_pending: true,
      has_template_for_type: true,
      slot_type: "weekday",
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)

    // User deletes → blocks become empty again on the SAME date.
    // The attemptedAutoDraftDates set must prevent a refire.
    await w.setProps({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
      has_template_for_type: true,
      slot_type: "weekday",
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)
  })

  it("(d) does NOT refire after restore_blocks([]) clears the schedule on the same date", async () => {
    const w = mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)

    // Auto-draft completed → blocks present, status still "draft" until
    // first edit.
    await w.setProps({
      schedule: makeSchedule("2026-05-04", "draft"),
      blocks: [makeBlock(1), makeBlock(2)],
      date: "2026-05-04",
      auto_draft_pending: true,
      has_template_for_type: true,
      slot_type: "weekday",
    })
    await flushPromises()

    // ⌘Z fires restore_blocks([]) → server reload returns blocks=[]
    // and status stays "draft". The watcher inputs (blocks.length,
    // auto_draft_pending) match the firing state again, but the date
    // is in attemptedAutoDraftDates so generateDraft must NOT fire.
    await w.setProps({
      schedule: makeSchedule("2026-05-04", "draft"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
      has_template_for_type: true,
      slot_type: "weekday",
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)
  })

  it("renders draft controls from the accepted response while Inertia props are unchanged", async () => {
    const date = "2026-05-04"
    const page = mountPage({ schedule: makeSchedule(date), blocks: [], date })
    await flushPromises()
    expect(page.findComponent({ name: "RegenerateDraftButton" }).exists()).toBe(true)
    expect(page.findComponent({ name: "DraftBadge" }).props("show")).toBe(false)
    await runScheduleMutation(revisionOwner, date, async () => ({ ok: true, data: {
      revision: 1, schedule: { ...makeSchedule(date), revision: 1 }, blocks: [makeBlock(1)],
    } }))
    await flushPromises()
    expect(page.props("blocks")).toEqual([])
    expect(page.props("schedule").revision).toBe(0)
    expect(page.findComponent({ name: "RegenerateDraftButton" }).exists()).toBe(false)
    expect(page.findComponent({ name: "DraftBadge" }).props("show")).toBe(true)
    await runScheduleMutation(revisionOwner, date, async () => ({ ok: true, data: {
      revision: 2, schedule: { ...makeSchedule(date, "active"), revision: 2 }, blocks: [makeBlock(1)],
    } }))
    await flushPromises()
    expect(page.findComponent({ name: "DraftBadge" }).props("show")).toBe(false)
  })

  it("passes undo registration to the draft owner", async () => {
    generateDraft.mockResolvedValueOnce({ ok: true, explanation: "Built from weekday template" })
    mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledWith("2026-05-04", pushUndo)
    // Accepted diff and revision validation belongs to useDraft.
    expect(pushUndo).not.toHaveBeenCalled()
  })

  it("does NOT push undo when generateDraft fails", async () => {
    generateDraft.mockResolvedValueOnce({ ok: false, status: 503, errors: { detail: "down" } })
    mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(generateDraft).toHaveBeenCalledTimes(1)
    expect(pushUndo).not.toHaveBeenCalled()
  })

  it("does not push draft undo after navigating away before the request resolves", async () => {
    // Auto-draft on day A while the user navigates to day B must not surface
    // an undo toast on B that could wipe A's freshly generated blocks.
    let resolveDraft: (v: { ok: boolean; explanation: string | null }) => void =
      () => {}
    generateDraft.mockReturnValueOnce(
      new Promise<{ ok: boolean; explanation: string | null }>((res) => {
        resolveDraft = res
      }),
    )
    const w = mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await nextTick()
    await w.setProps({ date: "2026-05-05", auto_draft_pending: false })
    expect(abandonInFlight).toHaveBeenCalled()
    resolveDraft({ ok: true, explanation: "drafted" })
    await flushPromises()
    expect(pushUndo).not.toHaveBeenCalled()
  })

  it("dismisses undo toast when navigating to another date", async () => {
    const w = mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: false,
    })
    await nextTick()
    dismissToast.mockClear()
    await w.setProps({ date: "2026-05-05" })
    expect(dismissToast).toHaveBeenCalled()
  })

  // KNOWN TEST GAP (feature 0026): `closeAddDialog()` in the date watcher is
  // not pinned here. Driving it requires the ExternalEventsPanel to render,
  // which needs a connected calendar — i.e. a file-wide `useCalendar` mock
  // that would alter rendering for every other test in this file. The
  // behaviour is exercised manually and the watcher's sibling resets
  // (abandonInFlight, dismissToast) are covered above, so an edit to that
  // watcher is unlikely to remove only the dialog line. Revisit if the panel
  // gains a lighter-weight test seam.
})

// --- feature 0008: viewport-driven chat surface routing ----------------

import ChatSidebar from "../src/components/ChatSidebar.vue"
import CommandBar from "../src/components/CommandBar.vue"
import { CHAT_SIDEBAR_OPEN_KEY } from "../src/utils/chatSidebarStorage"

describe("Schedule.vue chat surface routing (feature 0008)", () => {
  beforeEach(() => {
    stubLocalStorage()
    stubMatchMedia(false)
    resetExternalProviderMocks()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountStubbedSchedule() {
    return mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule("2026-05-04"),
        blocks: [],
        date: "2026-05-04",
        auto_draft_pending: false,
        has_template_for_type: true,
        slot_type: "weekday" as const,
      },
      global: { stubs: { ...STUBS, ChatSidebar: true } },
    })
  }

  function getSchedulePageStyle(w: VueWrapper): string {
    return (w.find(".schedule-page").attributes("style") ?? "")
      .replace(/\s+/g, "")
      .toLowerCase()
  }

  it("wide viewport — renders ChatSidebar, not CommandBar; --chat-sidebar-width: 380px", () => {
    stubMatchMedia(true)
    wrapper = mountStubbedSchedule()
    expect(wrapper.findComponent(ChatSidebar).exists()).toBe(true)
    expect(wrapper.findComponent(CommandBar).exists()).toBe(false)
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-sidebar-width:380px")
  })

  it("wide viewport with persisted collapse — renders ChatSidebar with --chat-sidebar-width: 32px", () => {
    localStorage.setItem(CHAT_SIDEBAR_OPEN_KEY, "false")
    stubMatchMedia(true)
    wrapper = mountStubbedSchedule()
    expect(wrapper.findComponent(ChatSidebar).exists()).toBe(true)
    expect(wrapper.findComponent(CommandBar).exists()).toBe(false)
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-sidebar-width:32px")
  })

  it("wide viewport updates --chat-sidebar-width reactively when ChatSidebar emits collapse", async () => {
    stubMatchMedia(true)
    wrapper = mountStubbedSchedule()
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-sidebar-width:380px")

    wrapper.findComponent(ChatSidebar).vm.$emit("update:open", false)
    await nextTick()

    expect(getSchedulePageStyle(wrapper)).toContain("--chat-sidebar-width:32px")
  })

  it("narrow viewport reserves the changing dock height on the whole page", async () => {
    stubMatchMedia(false)
    wrapper = mountStubbedSchedule()
    expect(wrapper.findComponent(CommandBar).exists()).toBe(true)
    expect(wrapper.findComponent(ChatSidebar).exists()).toBe(false)
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-sidebar-width:0px")
    const dock = wrapper.findComponent(CommandBar)
    dock.vm.$emit("height-change", 240)
    await nextTick()
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-dock-height:240px")
    dock.vm.$emit("height-change", 360)
    await nextTick()
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-dock-height:360px")
  })

  it("narrow viewport ignores persisted sidebar=false (precedence rule)", () => {
    // Even with localStorage saying the sidebar is collapsed, on a
    // narrow viewport the dock takes over and the CSS var collapses to
    // 0px so the schedule isn't padded for a non-existent sidebar.
    localStorage.setItem(CHAT_SIDEBAR_OPEN_KEY, "false")
    stubMatchMedia(false)
    wrapper = mountStubbedSchedule()
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-sidebar-width:0px")
  })

  it("flipping the matchMedia listener from narrow to wide unmounts CommandBar and mounts ChatSidebar", async () => {
    // Capture the change handler the composable registers so we can
    // fire a synthetic media-query change after mount and verify the
    // routing swaps the children without a remount loop.
    let changeHandler: ((e: { matches: boolean }) => void) | null = null
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        // Only the wide query's listener is the one this test flips; the
        // mobile query (feature 0113) registers its own.
        addEventListener: vi.fn((_evt: string, h: (e: { matches: boolean }) => void) => {
          if (query === "(min-width: 1024px)") changeHandler = h
        }),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
      })),
    )
    wrapper = mountStubbedSchedule()
    expect(wrapper.findComponent(CommandBar).exists()).toBe(true)
    expect(wrapper.findComponent(ChatSidebar).exists()).toBe(false)

    expect(changeHandler).not.toBeNull()
    wrapper.findComponent(CommandBar).vm.$emit("height-change", 300)
    await nextTick()
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-dock-height:300px")
    changeHandler!({ matches: true })
    await nextTick()

    expect(wrapper.findComponent(ChatSidebar).exists()).toBe(true)
    expect(wrapper.findComponent(CommandBar).exists()).toBe(false)
    expect(getSchedulePageStyle(wrapper)).toContain("--chat-dock-height:0px")
  })

  it(".schedule-page has box-sizing: content-box (CSS contract for padding-right model)", () => {
    stubMatchMedia(true)
    wrapper = mountStubbedSchedule()
    const el = wrapper.find(".schedule-page").element as HTMLElement
    expect(window.getComputedStyle(el).boxSizing).toBe("content-box")
  })
})

// --- feature 0031: external source poll gating -----------------------

type ScheduleExposed = {
  externalPollActive: boolean
  externalCalendarVisible: boolean
  tasksBranch: boolean
  calendarsBranch: boolean
  refreshExternalTasks: (date?: string) => void
  refreshExternalCalendars: (date?: string) => void
}

describe("Schedule.vue external source poll gating (feature 0031)", () => {
  const { setPlacement } = useExternalCalendarPlacement()

  beforeEach(() => {
    stubLocalStorage()
    stubMatchMedia(false)
    resetExternalProviderMocks()
    setPlacement("sidebar")
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(true))
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountPollSchedule() {
    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule("2026-05-04"),
        blocks: [],
        date: "2026-05-04",
        auto_draft_pending: false,
        has_template_for_type: true,
        slot_type: "weekday" as const,
        external_tasks_poll_interval: 60,
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap("2026-05-04", "UTC"),
      },
      global: {
        stubs: {
          ...STUBS,
          ChatSidebar: true,
          ExternalTasksSidebar: true,
          ExternalEventsPanel: true,
          ExternalCalendarPlacementToggle: true,
          AddToScheduleDialog: true,
        },
      },
    })
    return wrapper
  }

  function exposed(w: VueWrapper): ScheduleExposed {
    return w.vm as unknown as ScheduleExposed
  }

  it("passes an external event's calendar name into travel-rule matching", async () => {
    const event = {
      title: "Planning",
      start: "2026-05-04T09:00:00Z",
      end: "2026-05-04T10:00:00Z",
      calendar_name: "Work",
      all_day: false,
      external_uid: "calendar-rule-event",
      account_label: "",
    }
    const matchedRule = {
      id: 7,
      keyword: "",
      calendar_name: "Work",
      travel_there_minutes: 15,
      travel_back_minutes: 15,
      category: "work",
      order: 0,
    }
    // Matching uses the rules included in the same bootstrap as connections.
    matchTravelRule.mockReturnValueOnce(matchedRule)
    setPlacement("center")
    calendarState.statusKnown = true
    calendarState.connected = true
    const ExternalEventsPanelStub = defineComponent({
      emits: ["add-to-schedule"],
      setup(_, { emit }) {
        return () =>
          h(
            "button",
            {
              "data-testid": "add-external",
              onClick: () => emit("add-to-schedule", event),
            },
            "Add",
          )
      },
    })

    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule("2026-05-04"),
        blocks: [],
        date: "2026-05-04",
        auto_draft_pending: false,
        has_template_for_type: true,
        slot_type: "weekday" as const,
        external_tasks_poll_interval: 60,
        auth_user_id: 1,
        integration_bootstrap: { ...integrationBootstrap("2026-05-04", "UTC"), travel_rules: [matchedRule] },
      },
      global: {
        stubs: {
          ...STUBS,
          ExternalEventsPanel: ExternalEventsPanelStub,
          AddToScheduleDialog: {
            props: ["event", "matchedRule"],
            template: '<div data-testid="matched-rule">{{ matchedRule?.id }}</div>',
          },
          ExternalTasksSidebar: true,
          ExternalCalendarPlacementToggle: true,
        },
      },
    })
    await flushPromises()

    await wrapper.find('[data-testid="add-external"]').trigger("click")
    await flushPromises()

    expect(matchTravelRule).toHaveBeenCalledWith([matchedRule], "Planning", "Work")
    expect(wrapper.find('[data-testid="matched-rule"]').text()).toBe("7")
  })

  it("center placement + narrow viewport + calendar connected → poll active and fans out to refreshEvents", () => {
    stubMatchMedia(false)
    setPlacement("center")
    calendarState.statusKnown = true
    calendarState.connected = true

    const w = mountPollSchedule()
    const vm = exposed(w)

    expect(vm.externalCalendarVisible).toBe(true)
    expect(vm.calendarsBranch).toBe(true)
    expect(vm.tasksBranch).toBe(false)
    expect(vm.externalPollActive).toBe(true)
    expect(capturedPollOptions?.active.value).toBe(true)

    capturedPollOptions!.refresh("2026-05-04")
    expect(calendarRefreshEvents).toHaveBeenCalledWith("2026-05-04")
    expect(todoistRefreshTasks).not.toHaveBeenCalled()
    expect(habiticaRefreshTasks).not.toHaveBeenCalled()
  })

  it("sidebar placement + wide + open + calendar connected → poll active", () => {
    stubMatchMedia(true)
    setPlacement("sidebar")
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(true))
    calendarState.statusKnown = true
    calendarState.connected = true

    const w = mountPollSchedule()
    const vm = exposed(w)

    expect(vm.externalCalendarVisible).toBe(true)
    expect(vm.calendarsBranch).toBe(true)
    expect(vm.externalPollActive).toBe(true)

    capturedPollOptions!.refresh("2026-05-04")
    expect(calendarRefreshEvents).toHaveBeenCalledWith("2026-05-04")
  })

  it("sidebar placement + narrow + calendar connected → calendars branch false", () => {
    stubMatchMedia(false)
    setPlacement("sidebar")
    calendarState.statusKnown = true
    calendarState.connected = true

    const w = mountPollSchedule()
    const vm = exposed(w)

    expect(vm.externalCalendarVisible).toBe(false)
    expect(vm.calendarsBranch).toBe(false)
    expect(vm.externalPollActive).toBe(false)

    if (capturedPollOptions) {
      capturedPollOptions.refresh("2026-05-04")
    }
    expect(calendarRefreshEvents).not.toHaveBeenCalled()
  })

  it("sidebar placement + wide + collapsed + calendar connected → calendars branch false", () => {
    stubMatchMedia(true)
    setPlacement("sidebar")
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(false))
    calendarState.statusKnown = true
    calendarState.connected = true

    const w = mountPollSchedule()
    const vm = exposed(w)

    expect(vm.externalCalendarVisible).toBe(false)
    expect(vm.calendarsBranch).toBe(false)
    expect(vm.externalPollActive).toBe(false)

    if (capturedPollOptions) {
      capturedPollOptions.refresh("2026-05-04")
    }
    expect(calendarRefreshEvents).not.toHaveBeenCalled()
  })

  it("calendar-only tick (task rail closed) calls calendar refresh not task refresh", () => {
    stubMatchMedia(true)
    setPlacement("center")
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(false))
    calendarState.statusKnown = true
    calendarState.connected = true
    todoistState.statusKnown = true
    todoistState.connected = true

    const w = mountPollSchedule()
    const vm = exposed(w)

    expect(vm.calendarsBranch).toBe(true)
    expect(vm.tasksBranch).toBe(false)
    expect(vm.externalPollActive).toBe(true)

    capturedPollOptions!.refresh("2026-05-04")
    expect(calendarRefreshEvents).toHaveBeenCalledWith("2026-05-04")
    expect(todoistRefreshTasks).not.toHaveBeenCalled()
  })

  it("tasks-only tick does not call calendar refresh", () => {
    stubMatchMedia(true)
    setPlacement("sidebar")
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(true))
    todoistState.statusKnown = true
    todoistState.connected = true
    // Calendar connected but sidebar-placed panel would be visible too —
    // leave calendar disconnected so only the tasks branch is active.
    calendarState.statusKnown = true
    calendarState.connected = false

    const w = mountPollSchedule()
    const vm = exposed(w)

    expect(vm.tasksBranch).toBe(true)
    expect(vm.calendarsBranch).toBe(false)
    expect(vm.externalPollActive).toBe(true)

    capturedPollOptions!.refresh("2026-05-04")
    expect(todoistRefreshTasks).toHaveBeenCalledWith("2026-05-04")
    expect(calendarRefreshEvents).not.toHaveBeenCalled()
    expect(googleCalendarRefreshEvents).not.toHaveBeenCalled()
  })

  it("disconnected provider's refreshEvents is never called", () => {
    stubMatchMedia(false)
    setPlacement("center")
    calendarState.statusKnown = true
    calendarState.connected = true
    googleCalendarState.statusKnown = true
    googleCalendarState.connected = false

    mountPollSchedule()
    capturedPollOptions!.refresh("2026-05-04")

    expect(calendarRefreshEvents).toHaveBeenCalledWith("2026-05-04")
    expect(googleCalendarRefreshEvents).not.toHaveBeenCalled()
  })
})

describe("Schedule.vue calendar events stay off the timeline (0106)", () => {
  const { setPlacement } = useExternalCalendarPlacement()
  const DATE = "2026-05-04"
  const event = {
    title: "Dentist",
    start: `${DATE}T14:00:00Z`,
    end: `${DATE}T15:00:00Z`,
    calendar_name: "Personal",
    all_day: false,
    external_uid: "isolation-event",
    account_label: "",
  }
  const blocks: TimeBlock[] = [
    { ...makeBlock(1), start_time: "11:45", end_time: "12:10", sort_order: 0 },
    { ...makeBlock(2), start_time: "15:00", end_time: "16:00", sort_order: 1 },
  ]

  beforeEach(() => {
    stubLocalStorage()
    stubMatchMedia(true)
    resetExternalProviderMocks()
    setPlacement("sidebar")
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(true))
    document.documentElement.dataset.theme = "dark_4a"
    calendarState.statusKnown = true
    calendarState.connected = true
    calendarState.events = [event]
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    delete document.documentElement.dataset.theme
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountIsolation() {
    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule(DATE, "active"),
        blocks,
        date: DATE,
        auto_draft_pending: false,
        has_template_for_type: true,
        slot_type: "weekday" as const,
        schedule_window: { start: "06:00", end: "23:00", time_zone: "UTC" },
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap(DATE, "UTC"),
      },
      global: {
        stubs: {
          ...STUBS,
          AddToScheduleDialog: {
            props: ["event"],
            template: '<div data-testid="add-dialog">{{ event.external_uid }}</div>',
          },
        },
      },
    })
    return wrapper
  }

  function timelineItems(w: VueWrapper) {
    const timeline = w.findComponent({ name: "Timeline4a" })
    expect(timeline.exists()).toBe(true)
    const presentation = timeline.props("presentation") as {
      positionedItems: { item: { type: string; start_time: string; end_time: string; duration_minutes: number; block?: TimeBlock } }[]
    }
    return presentation.positionedItems.map((p) => p.item)
  }

  it("renders no timeline item for an event that was not added", async () => {
    const w = mountIsolation()
    await flushPromises()
    const items = timelineItems(w)
    const blockIds = items.filter((i) => i.type === "block").map((i) => i.block?.id)
    expect(blockIds).toEqual([1, 2])
    expect(items.some((i) => i.start_time === "14:00")).toBe(false)
  })

  it("keeps 12:10–15:00 as one free gap of 170 minutes", async () => {
    const w = mountIsolation()
    await flushPromises()
    const gaps = timelineItems(w).filter((i) => i.type === "gap")
    const midDay = gaps.filter((g) => g.start_time >= "12:10" && g.end_time <= "15:00")
    expect(midDay).toHaveLength(1)
    expect(midDay[0]).toMatchObject({ start_time: "12:10", end_time: "15:00", duration_minutes: 170 })
  })

  it("shows the event only inside the sources rail with an Add to schedule button", async () => {
    const w = mountIsolation()
    await flushPromises()
    const rail = w.find('[data-testid="external-rail-4a"]')
    expect(rail.exists()).toBe(true)
    const rows = w.findAll('[data-testid="external-event"]')
    expect(rows).toHaveLength(1)
    expect(rail.element.contains(rows[0].element)).toBe(true)
    expect(rows[0].find('[data-testid="add-to-schedule"]').exists()).toBe(true)
    expect(w.find('[data-testid="timeline-4a"]').text()).not.toContain("Dentist")
  })

  it("opens the import dialog on Add to schedule and creates no block by itself", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }))
    vi.stubGlobal("fetch", fetchSpy)
    const w = mountIsolation()
    await flushPromises()
    fetchSpy.mockClear()
    createBlockSpy.mockClear()
    await w.find('[data-testid="add-to-schedule"]').trigger("click")
    await flushPromises()
    expect(w.find('[data-testid="add-dialog"]').text()).toBe("isolation-event")
    expect(createBlockSpy).not.toHaveBeenCalled()
    const writes = fetchSpy.mock.calls.filter(([, init]) => (init?.method ?? "GET").toUpperCase() !== "GET")
    expect(writes).toEqual([])
    const blockIds = timelineItems(w).filter((i) => i.type === "block").map((i) => i.block?.id)
    expect(blockIds).toEqual([1, 2])
  })
})

describe("Schedule.vue Dark 4a gap add (0106)", () => {
  const DATE = "2026-05-04"
  const blocks: TimeBlock[] = [
    { ...makeBlock(1), start_time: "11:45", end_time: "12:10", sort_order: 0 },
    { ...makeBlock(2), start_time: "15:00", end_time: "16:00", sort_order: 1 },
  ]

  beforeEach(() => {
    stubLocalStorage()
    stubMatchMedia(true)
    resetExternalProviderMocks()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    delete document.documentElement.dataset.theme
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountWithForm(theme: "dark_4a" | "classic") {
    document.documentElement.dataset.theme = theme
    const { AddBlockForm: _form, ...stubs } = STUBS
    void _form
    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule(DATE, "active"),
        blocks,
        date: DATE,
        schedule_window: { start: "06:00", end: "23:00", time_zone: "UTC" },
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap(DATE, "UTC"),
      },
      global: { stubs: { ...stubs, GapSlot: false } },
    })
    return wrapper
  }

  function midDayRow(w: VueWrapper) {
    return w.findAll('[data-testid="gap-row-4a"]').find((row) => row.text().includes("12:10–15:00"))!
  }

  it("reopens the form when the same gap is activated after Cancel", async () => {
    const w = mountWithForm("dark_4a")
    await flushPromises()
    await midDayRow(w).trigger("click")
    expect(w.find(".add-form").exists()).toBe(true)
    const times = w.findAll('.add-form input[type="time"]').map((i) => (i.element as HTMLInputElement).value)
    expect(times).toEqual(["12:10", "15:00"])
    await w.get(".add-form .cancel-btn").trigger("click")
    expect(w.find(".add-form").exists()).toBe(false)
    await midDayRow(w).trigger("click")
    expect(w.find(".add-form").exists()).toBe(true)
  })

  it("keeps the classic gap handler unchanged", async () => {
    const w = mountWithForm("classic")
    await flushPromises()
    expect(w.find('[data-testid="gap-row-4a"]').exists()).toBe(false)
    const gap = w.findAll(".gap-slot").find((g) => g.text().includes("12:10 – 15:00"))!
    await gap.trigger("click")
    expect(w.find(".add-form").exists()).toBe(true)
    await w.get(".add-form .cancel-btn").trigger("click")
    await gap.trigger("click")
    // Classic keeps today's behaviour: unchanged props do not reopen the form.
    expect(w.find(".add-form").exists()).toBe(false)
  })
})

describe("Schedule.vue Dark 4a empty day and header (0106)", () => {
  const DATE = "2026-11-22"

  beforeEach(() => {
    stubLocalStorage()
    stubMatchMedia(true)
    resetExternalProviderMocks()
    Element.prototype.scrollIntoView = vi.fn()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    delete document.documentElement.dataset.theme
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountDay(opts: {
    theme?: "dark_4a" | "classic"
    hasTemplate?: boolean
    blocks?: TimeBlock[]
    realChat?: boolean
    realRegen?: boolean
  } = {}) {
    document.documentElement.dataset.theme = opts.theme ?? "dark_4a"
    const stubs: Record<string, unknown> = { ...STUBS }
    if (opts.realChat) {
      delete stubs.ChatSidebar
      delete stubs.CommandBar
    }
    if (opts.realRegen) delete stubs.RegenerateDraftButton
    wrapper = mount(Schedule, {
      attachTo: document.body,
      props: {
        categories: makeCategories(),
        schedule: makeSchedule(DATE, "draft"),
        blocks: opts.blocks ?? [],
        date: DATE,
        has_template_for_type: opts.hasTemplate ?? false,
        slot_type: "weekend" as const,
        schedule_window: { start: "06:00", end: "23:00", time_zone: "UTC" },
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap(DATE, "UTC"),
      },
      global: { stubs },
    })
    return wrapper
  }

  it("shows the empty state instead of the timeline on a 4a day with no template and no blocks", async () => {
    const w = mountDay()
    await flushPromises()
    expect(w.find('[data-testid="empty-day-state"]').text()).toContain("No template for Sunday")
    expect(w.find('[data-testid="timeline-4a"]').exists()).toBe(false)
  })

  it("keeps the timeline when a template exists", async () => {
    const w = mountDay({ hasTemplate: true })
    await flushPromises()
    expect(w.find('[data-testid="empty-day-state"]').exists()).toBe(false)
    expect(w.find('[data-testid="timeline-4a"]').exists()).toBe(true)
  })

  it("hides the header warning in 4a and keeps it in classic", async () => {
    const dark = mountDay({ realRegen: true })
    await flushPromises()
    expect(dark.find(".regen-btn").exists()).toBe(true)
    expect(dark.find(".reason").exists()).toBe(false)
    dark.unmount()
    wrapper = null
    const classic = mountDay({ theme: "classic", realRegen: true })
    await flushPromises()
    expect(classic.find(".reason").text()).toBe("No weekend template configured.")
  })

  it("Plan with AI focuses the chat textarea with a collapsed wide sidebar", async () => {
    localStorage.setItem("day-forge:chat-sidebar:open", JSON.stringify(false))
    const w = mountDay({ realChat: true })
    await flushPromises()
    expect(w.find('[data-testid="chat-input"]').exists()).toBe(false)
    await w.get('[data-testid="empty-day-plan-with-ai"]').trigger("click")
    await flushPromises()
    const input = w.get('[data-testid="chat-input"]').element
    expect(document.activeElement).toBe(input)
  })

  it("Plan with AI focuses the dock below 1024px", async () => {
    stubMatchMedia(false)
    const w = mountDay({ realChat: true })
    await flushPromises()
    await w.get('[data-testid="empty-day-plan-with-ai"]').trigger("click")
    await flushPromises()
    const input = w.get('[data-testid="chat-input"]')
    expect(input.classes()).toContain("variant-dock")
    expect(document.activeElement).toBe(input.element)
  })

  it("Plan with AI focuses the chat status when the input is disabled", async () => {
    const { useChat } = await import("../src/composables/useChat")
    const w = mountDay({ realChat: true })
    await flushPromises()
    useChat(revisionOwner).isProcessing.value = true
    await flushPromises()
    await w.get('[data-testid="empty-day-plan-with-ai"]').trigger("click")
    await flushPromises()
    expect(document.activeElement).toBe(w.get('[data-testid="chat-status"]').element)
    useChat(revisionOwner).isProcessing.value = false
  })
})

describe("Schedule.vue Dark 4a narrow calendar fallback (0106)", () => {
  const { setPlacement, placement } = useExternalCalendarPlacement()
  let changeHandler: ((e: { matches: boolean }) => void) | null = null

  function stubViewport(wide: boolean) {
    changeHandler = null
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      // The mobile query (feature 0113) is never true in a wide/narrow-rail test.
      matches: query.includes("max-width") ? false : wide, media: query, onchange: null,
      addEventListener: vi.fn((_evt: string, h: (e: { matches: boolean }) => void) => {
        if (!query.includes("max-width")) changeHandler = h
      }),
      removeEventListener: vi.fn(), dispatchEvent: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(),
    })))
  }

  beforeEach(() => {
    stubLocalStorage()
    resetExternalProviderMocks()
    setPlacement("sidebar")
    calendarState.statusKnown = true
    calendarState.connected = true
    calendarState.events = [{
      title: "Dentist", start: "2026-05-04T14:00:00Z", end: "2026-05-04T15:00:00Z",
      calendar_name: "Personal", all_day: false, external_uid: "narrow-event", account_label: "",
    }]
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    delete document.documentElement.dataset.theme
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountNarrow(theme: "dark_4a" | "classic") {
    document.documentElement.dataset.theme = theme
    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule("2026-05-04", "active"),
        blocks: [],
        date: "2026-05-04",
        has_template_for_type: true,
        external_tasks_poll_interval: 60,
        schedule_window: { start: "06:00", end: "23:00", time_zone: "UTC" },
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap("2026-05-04", "UTC"),
      },
      global: { stubs: { ...STUBS, AddToScheduleDialog: true } },
    })
    return wrapper
  }

  it("renders and polls the calendar panel below 1024px in Dark 4a with sidebar placement", async () => {
    stubViewport(false)
    const w = mountNarrow("dark_4a")
    await flushPromises()
    const vm = w.vm as unknown as ScheduleExposed
    expect(vm.calendarsBranch).toBe(true)
    expect(vm.externalPollActive).toBe(true)
    const panel = w.get('section[aria-label="External calendar events"]')
    // Rendered after the schedule body, with the Dark 4a copy.
    const body = w.get(".schedule-body").element
    expect(body.compareDocumentPosition(panel.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(panel.get('[data-testid="add-to-schedule"]').text()).toBe("Add to schedule")
    expect(placement.value).toBe("sidebar")
  })

  it("returns to the stored placement when resized to wide", async () => {
    stubViewport(false)
    const w = mountNarrow("dark_4a")
    await flushPromises()
    expect(w.find('section[aria-label="External calendar events"]').exists()).toBe(true)
    changeHandler!({ matches: true })
    await flushPromises()
    const vm = w.vm as unknown as ScheduleExposed
    expect(placement.value).toBe("sidebar")
    // Wide: the calendar lives in the sources rail again, not the centre.
    expect(w.find(".schedule-body ~ section[aria-label='External calendar events']").exists()).toBe(false)
    expect(w.find('[data-testid="external-rail-4a"]').exists()).toBe(true)
    expect(vm.calendarsBranch).toBe(true)
  })

  it("keeps narrow behaviour unchanged in classic", async () => {
    stubViewport(false)
    const w = mountNarrow("classic")
    await flushPromises()
    const vm = w.vm as unknown as ScheduleExposed
    expect(vm.calendarsBranch).toBe(false)
    expect(w.find('section[aria-label="External calendar events"]').exists()).toBe(false)
  })
})

describe("Schedule.vue logout footer by theme (0106)", () => {
  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    delete document.documentElement.dataset.theme
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountTheme(theme: "dark_4a" | "classic") {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: !query.includes("max-width"), media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    })))
    stubLocalStorage()
    resetExternalProviderMocks()
    document.documentElement.dataset.theme = theme
    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule("2026-05-04", "active"),
        blocks: [],
        date: "2026-05-04",
        has_template_for_type: true,
        external_tasks_poll_interval: 0,
        schedule_window: { start: "06:00", end: "23:00", time_zone: "UTC" },
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap("2026-05-04", "UTC"),
      },
      global: { stubs: { ...STUBS, AddToScheduleDialog: true } },
    })
    return wrapper
  }

  it("renders no logout control in Dark 4a", () => {
    const w = mountTheme("dark_4a")
    expect(w.find(".logout-footer").exists()).toBe(false)
    expect(w.findAll("button").some((b) => /log ?out/i.test(b.text()))).toBe(false)
  })

  it("keeps the logout footer in classic", () => {
    const w = mountTheme("classic")
    expect(w.get(".logout-footer .logout-btn").text()).toBe("Logout")
  })
})

// Feature 0112 / issue #229: Schedule left open across saved-zone midnight
// must restyle external events from the page clock, not a cached todayString().
describe("Schedule.vue external calendar past-state at midnight (0112)", () => {
  const { setPlacement } = useExternalCalendarPlacement()
  const ZONE = "Asia/Qatar"
  const MAY_7 = "2026-05-07"
  // 23:59:30 on 7 May in Asia/Qatar. Sixty seconds later is 00:00:30 on
  // 8 May there, while UTC is still 7 May 21:00 — so a browser/UTC today
  // would stay stale.
  const BEFORE_QATAR_MIDNIGHT = "2026-05-07T20:59:30Z"
  const overnight = {
    title: "Late standup",
    start: "2026-05-07T20:00:00Z",
    end: "2026-05-07T21:30:00Z",
    calendar_name: "Team",
    all_day: false,
    external_uid: "overnight-qatar",
    account_label: "",
  }
  const evening = {
    title: "Dinner",
    start: "2026-05-07T13:00:00Z",
    end: "2026-05-07T14:00:00Z",
    calendar_name: "Personal",
    all_day: false,
    external_uid: "dinner-qatar",
    account_label: "",
  }

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(BEFORE_QATAR_MIDNIGHT))
    stubLocalStorage()
    stubMatchMedia(false)
    resetExternalProviderMocks()
    setPlacement("center")
    calendarState.statusKnown = true
    calendarState.connected = true
    calendarState.events = [overnight]
    document.documentElement.dataset.theme = "classic"
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    localStorage.clear()
    delete document.documentElement.dataset.theme
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  function mountOpenSchedule(opts: { placement: "center" | "sidebar"; wide: boolean }) {
    setPlacement(opts.placement)
    stubMatchMedia(opts.wide)
    if (opts.wide) {
      localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(true))
    }
    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule(MAY_7),
        blocks: [],
        date: MAY_7,
        auto_draft_pending: false,
        has_template_for_type: true,
        slot_type: "weekday" as const,
        schedule_window: { start: "06:00", end: "23:00", time_zone: ZONE },
        external_tasks_poll_interval: 60,
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap(MAY_7, ZONE),
      },
      global: {
        stubs: {
          ...STUBS,
          ChatSidebar: true,
          AddToScheduleDialog: true,
        },
      },
    })
    return wrapper
  }

  async function crossSavedZoneMidnight() {
    vi.advanceTimersByTime(60_000)
    await nextTick()
  }

  it("center panel marks an overnight event past after saved-zone midnight without remounting", async () => {
    const w = mountOpenSchedule({ placement: "center", wide: false })
    const panel = w.getComponent(ExternalEventsPanel)
    expect(panel.props("todayDate")).toBe(MAY_7)
    expect(panel.props("variant")).toBe("center")
    const item = w.get('[data-testid="external-event"]')
    expect(item.classes()).not.toContain("ee-item--past")

    await crossSavedZoneMidnight()

    expect(todayString("UTC")).toBe(MAY_7)
    expect(todayString(ZONE)).toBe("2026-05-08")
    expect(panel.props("todayDate")).toBe("2026-05-08")
    expect(item.classes()).toContain("ee-item--past")
  })

  it("sidebar panel supplies todayDate and restyles after the same rollover", async () => {
    const w = mountOpenSchedule({ placement: "sidebar", wide: true })
    const panel = w.getComponent(ExternalEventsPanel)
    expect(panel.props("todayDate")).toBe(MAY_7)
    expect(panel.props("variant")).toBe("sidebar")
    const item = w.get('[data-testid="external-event"]')
    expect(item.classes()).not.toContain("ee-item--past")

    await crossSavedZoneMidnight()

    expect(panel.props("todayDate")).toBe("2026-05-08")
    expect(item.classes()).toContain("ee-item--past")
  })

  it("same-day clock ticks keep a later event unfaded", async () => {
    vi.setSystemTime(new Date("2026-05-07T12:00:00Z"))
    calendarState.events = [evening]
    const w = mountOpenSchedule({ placement: "center", wide: false })
    const item = w.get('[data-testid="external-event"]')
    expect(item.classes()).not.toContain("ee-item--past")

    vi.advanceTimersByTime(60_000)
    await nextTick()

    expect(item.classes()).not.toContain("ee-item--past")
    expect(w.getComponent(ExternalEventsPanel).props("todayDate")).toBe(MAY_7)
  })
})

describe("Schedule.vue Dark 4a mobile header (0113)", () => {
  const { setPlacement } = useExternalCalendarPlacement()

  function stubViewport(mobile: boolean) {
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width") ? mobile : false, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    })))
  }

  function mountMobile(theme: "dark_4a" | "classic", mobile: boolean) {
    stubViewport(mobile)
    document.documentElement.dataset.theme = theme
    wrapper = mount(Schedule, {
      props: {
        categories: makeCategories(),
        schedule: makeSchedule("2026-05-04", "active"),
        blocks: [],
        date: "2026-05-04",
        has_template_for_type: true,
        external_tasks_poll_interval: 60,
        schedule_window: { start: "06:00", end: "23:00", time_zone: "UTC" },
        auth_user_id: 1,
        integration_bootstrap: integrationBootstrap("2026-05-04", "UTC"),
      },
      attachTo: document.body,
      global: { stubs: { ...STUBS, AddToScheduleDialog: true, ShowIndicatorButton: true, TimeZoneMismatchPrompt: true } },
    })
    return wrapper
  }

  beforeEach(() => {
    stubLocalStorage()
    resetExternalProviderMocks()
    setPlacement("sidebar")
    calendarState.statusKnown = true
    calendarState.connected = true
    calendarState.events = [{
      title: "Dentist", start: "2026-05-04T14:00:00Z", end: "2026-05-04T15:00:00Z",
      calendar_name: "Personal", all_day: false, external_uid: "mobile-event", account_label: "",
    }]
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    delete document.documentElement.dataset.theme
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it("swaps the date navigator for the mobile header and drops the desktop-only controls", async () => {
    const w = mountMobile("dark_4a", true)
    await flushPromises()
    expect(w.find('[data-testid="mobile-header"]').exists()).toBe(true)
    expect(w.find('[data-testid="mobile-date"]').text()).toBe("Mon, May 4")
    expect(w.findComponent({ name: "ShowIndicatorButton" }).exists()).toBe(false)
    expect(w.findComponent({ name: "TimeZoneMismatchPrompt" }).exists()).toBe(false)
    expect(w.find(".undo-btn").exists()).toBe(false)
    expect(w.find(".analytics-link").exists()).toBe(false)
  })

  it("keeps the desktop header in classic and in Dark 4a above 640px", async () => {
    const classic = mountMobile("classic", true)
    await flushPromises()
    expect(classic.find('[data-testid="mobile-header"]').exists()).toBe(false)
    expect(classic.find(".undo-btn").exists()).toBe(true)
    classic.unmount()
    const wide = mountMobile("dark_4a", false)
    await flushPromises()
    expect(wide.find('[data-testid="mobile-header"]').exists()).toBe(false)
    expect(wide.find(".undo-btn").exists()).toBe(true)
  })

  it("moves the calendar panel into the gear menu's Calendars sheet and keeps polling", async () => {
    const w = mountMobile("dark_4a", true)
    await flushPromises()
    const vm = w.vm as unknown as ScheduleExposed
    expect(w.find('section[aria-label="External calendar events"]').exists()).toBe(false)
    expect(vm.externalPollActive).toBe(true)
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    await w.get('[data-testid="mobile-menu-calendars"]').trigger("click")
    await flushPromises()
    expect(w.find('[data-testid="mobile-menu"]').exists()).toBe(false)
    const sheet = w.get('[data-testid="mobile-calendars"]')
    expect(sheet.find('section[aria-label="External calendar events"]').exists()).toBe(true)
    await sheet.trigger("keydown", { key: "Escape" })
    await flushPromises()
    expect(w.find('[data-testid="mobile-calendars"]').exists()).toBe(false)
    expect(document.activeElement).toBe(w.get('[data-testid="mobile-gear"]').element)
  })

  it("logs out from the menu", async () => {
    const w = mountMobile("dark_4a", true)
    await flushPromises()
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    await w.get('[data-testid="mobile-menu-logout"]').trigger("click")
    expect(router.post).toHaveBeenCalledWith("/accounts/logout/")
  })
})
