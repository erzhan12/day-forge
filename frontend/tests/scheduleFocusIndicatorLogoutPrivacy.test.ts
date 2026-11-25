/**
 * Issue #212 acceptance: real Schedule under FocusIndicatorHost must not leave
 * outgoing blocks/categories in the root controller after Login unmount.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { defineComponent, h, inject, nextTick, reactive, ref, type Ref } from "vue"
import { makeCategories } from "./helpers/schedule"
import FocusIndicatorHost from "../src/components/FocusIndicatorHost.vue"
import {
  FocusIndicatorControllerKey,
  type FocusIndicatorController,
} from "../src/composables/useFocusIndicatorController"
import {
  clearFocusIndicatorShouldBeOpen,
  readFocusIndicatorShouldBeOpen,
} from "../src/utils/focusIndicatorStorage"
import type { Schedule as ScheduleType, TimeBlock, UserCategory } from "../src/types"

const page = reactive<{
  component?: string
  props: { auth_user_id?: number | null; categories?: unknown }
}>({
  component: "Schedule",
  props: { auth_user_id: 7 },
})

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn(), visit: vi.fn(), post: vi.fn() },
  Link: { name: "Link", template: "<a><slot /></a>" },
  usePage: () => page,
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

vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    reorderBlocks: vi.fn(),
    createBlock: vi.fn(),
    updateBlock: vi.fn().mockResolvedValue({ ok: true }),
    deleteBlock: vi.fn(),
    restoreBlocks: vi.fn(),
  }),
}))

vi.mock("../src/composables/useUndo", () => ({
  useUndo: () => ({
    undoStack: ref([]),
    canUndo: ref(false),
    currentToast: ref(null),
    pushUndo: vi.fn(),
    performUndo: vi.fn(),
    snapshotBlocks: vi.fn(() => []),
    dismissToast: vi.fn(),
  }),
}))

const nowMinutes = ref<number | null>(570)
const nowDate = ref<string | null>("2026-08-12")
const todayDate = ref("2026-08-12")
const currentHHMM = ref("09:30")
vi.mock("../src/composables/useNowMinutes", () => ({
  useNowMinutes: () => ({ nowMinutes, nowDate, todayDate, currentHHMM }),
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
    frozenRenderBounds: ref(null),
    frozenNowMinutes: ref(null),
    frozenPxPerMinute: ref(null),
    frozenTimelineOriginMinutes: ref(null),
    frozenWindow: ref(null),
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
vi.mock("../src/composables/useCalendar", () => ({
  useCalendar: () => ({
    state: makeProviderState(),
    fetchEvents: vi.fn(),
    refreshEvents: vi.fn(),
    fetchAccountStatus: vi.fn(),
    invalidateAccount: vi.fn(),
  }),
}))
vi.mock("../src/composables/useGoogleCalendar", () => ({
  useGoogleCalendar: () => ({
    state: makeProviderState(),
    fetchEvents: vi.fn(),
    refreshEvents: vi.fn(),
    fetchAccountStatus: vi.fn(),
    invalidateAccount: vi.fn(),
  }),
}))
vi.mock("../src/composables/useTodoist", () => ({
  useTodoist: () => ({
    state: makeProviderState(),
    fetchTasks: vi.fn(),
    refreshTasks: vi.fn(),
    completeTask: vi.fn(),
    fetchAccountStatus: vi.fn(),
    invalidateAccount: vi.fn(),
  }),
}))
vi.mock("../src/composables/useHabitica", () => ({
  useHabitica: () => ({
    state: makeProviderState(),
    fetchTasks: vi.fn(),
    refreshTasks: vi.fn(),
    completeTask: vi.fn(),
    fetchAccountStatus: vi.fn(),
    invalidateAccount: vi.fn(),
  }),
}))
vi.mock("../src/composables/useExternalSourcePoll", () => ({
  useExternalSourcePoll: () => {},
}))

import Schedule from "../src/pages/Schedule.vue"

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

function makeBlock(): TimeBlock {
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

describe("Schedule under FocusIndicatorHost logout privacy (#212)", () => {
  let controller: FocusIndicatorController | null = null

  const Probe = defineComponent({
    setup() {
      controller = inject(FocusIndicatorControllerKey)!
      return () => h("div")
    },
  })

  beforeEach(() => {
    stubMatchMedia()
    page.component = "Schedule"
    page.props = { auth_user_id: 7 }
    nowMinutes.value = 570
    nowDate.value = "2026-08-12"
    controller = null
    clearFocusIndicatorShouldBeOpen()
  })

  afterEach(() => {
    delete (window as unknown as { documentPictureInPicture?: unknown }).documentPictureInPicture
    clearFocusIndicatorShouldBeOpen()
    vi.unstubAllGlobals()
  })

  it("clears retained blocks and categories when real Schedule unmounts after Login", async () => {
    const categories: UserCategory[] = makeCategories()
    const blocks = [makeBlock()]
    const win = makeFakeWindow()
    const requestWindow = installFakePip(win)
    const showingSchedule = ref(true)

    const wrapper = mount(FocusIndicatorHost, {
      slots: {
        default: () => [
          h(Probe),
          showingSchedule.value
            ? h(Schedule, {
                schedule: { id: 1, date: "2026-08-12", status: "active", revision: 0 } as ScheduleType,
                blocks,
                date: "2026-08-12",
                categories,
                auto_draft_pending: false,
                has_template_for_type: true,
                slot_type: "weekday",
                auth_user_id: 7,
                integration_bootstrap: {
                  snapshot_id: "pip-2026-08-12",
                  user_id: 7,
                  date: "2026-08-12",
                  time_zone: "UTC",
                  connected: { apple: false, google: false, todoist: false, habitica: false },
                  travel_rules: [],
                },
              })
            : null,
        ],
      },
      global: { stubs: STUBS },
    })

    // Schedule publishes into the Host controller on mount.
    await nextTick()
    expect(controller).not.toBeNull()
    expect(controller!.indicatorActive.value).toBe(true)
    expect(controller!.retainedSnapshot().blocks).toHaveLength(1)
    expect(controller!.retainedSnapshot().categories.length).toBeGreaterThan(0)
    const staleGeneration = controller!.publicationGeneration()

    await controller!.focusIndicator.open()
    await flushPromises()
    expect(requestWindow).toHaveBeenCalledTimes(1)
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)

    // Logout shape: Inertia swaps to Login (and null user) before Schedule unmounts.
    page.component = "Login"
    page.props = { auth_user_id: null }
    await nextTick()
    showingSchedule.value = false
    await nextTick()

    expect(win.close).toHaveBeenCalledTimes(1)
    expect(controller!.indicatorActive.value).toBe(false)
    expect(controller!.retainedSnapshot()).toEqual({ date: "", blocks: [], categories: [] })
    expect(controller!.publishIfGenerationMatches(staleGeneration, "2026-08-12", blocks, categories)).toBe(
      false,
    )
    const generationAfterClear = controller!.publicationGeneration()
    expect(
      controller!.publishIfGenerationMatches(generationAfterClear, "2026-08-12", blocks, categories),
    ).toBe(false)
    expect("publish" in controller!).toBe(false)
    expect(controller!.retainedSnapshot()).toEqual({ date: "", blocks: [], categories: [] })
    expect(requestWindow).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })
})
