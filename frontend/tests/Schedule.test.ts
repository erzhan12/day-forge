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
import { ref, type Ref } from "vue"

// --- mocks ---------------------------------------------------------------

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn(), visit: vi.fn(), post: vi.fn() },
  Link: { name: "Link", template: "<a><slot /></a>" },
}))

const generateDraft = vi.fn()
// Default: succeed with no explanation so runDraft pushes a "draft" undo.
generateDraft.mockResolvedValue({ ok: true, explanation: null })

const isGeneratingDraft = ref(false)
const lastDraftError: Ref<string | null> = ref(null)

vi.mock("../src/composables/useDraft", () => ({
  useDraft: () => ({
    isGeneratingDraft,
    lastDraftError,
    generateDraft,
    clearDraftError: vi.fn(),
  }),
}))

vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    reorderBlocks: vi.fn(),
    createBlock: vi.fn(),
    updateBlock: vi.fn(),
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

vi.mock("../src/composables/useDrag", () => ({
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

// Import AFTER all mocks so the SUT picks them up.
import Schedule from "../src/pages/Schedule.vue"
import type { Schedule as ScheduleType, TimeBlock } from "../src/types"

// --- helpers -------------------------------------------------------------

function makeSchedule(date: string, status: ScheduleType["status"] = "draft"): ScheduleType {
  return { id: 1, date, status }
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
  DraftBadge: true,
  RegenerateDraftButton: true,
}

let wrapper: VueWrapper | null = null

function mountPage(props: {
  schedule: ScheduleType
  blocks: TimeBlock[]
  date: string
  auto_draft_pending?: boolean
  has_template_for_type?: boolean
  slot_type?: "weekday" | "weekend"
}) {
  wrapper = mount(Schedule, {
    props: {
      auto_draft_pending: false,
      has_template_for_type: true,
      slot_type: "weekday" as const,
      ...props,
    },
    global: { stubs: STUBS },
  })
  return wrapper
}

describe("Schedule.vue auto-draft watcher", () => {
  beforeEach(() => {
    generateDraft.mockClear()
    generateDraft.mockResolvedValue({ ok: true, explanation: null })
    pushUndo.mockClear()
    snapshotBlocks.mockClear()
    isGeneratingDraft.value = false
    lastDraftError.value = null
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
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
    expect(generateDraft).toHaveBeenCalledWith("2026-05-04")
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
    expect(generateDraft).toHaveBeenLastCalledWith("2026-05-04")

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
    expect(generateDraft).toHaveBeenLastCalledWith("2026-05-05")
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

  it("pushes a 'draft' undo entry when generateDraft resolves successfully", async () => {
    generateDraft.mockResolvedValueOnce({ ok: true, explanation: "Built from weekday template" })
    mountPage({
      schedule: makeSchedule("2026-05-04"),
      blocks: [],
      date: "2026-05-04",
      auto_draft_pending: true,
    })
    await flushPromises()
    expect(pushUndo).toHaveBeenCalledTimes(1)
    const action = pushUndo.mock.calls[0][0]
    expect(action.type).toBe("draft")
    expect(action.scheduleDate).toBe("2026-05-04")
    expect(action.previousBlocks).toEqual([])
    expect(action.description).toBe("Built from weekday template")
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
})
