import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { ref } from "vue"
import type { TimeBlock, UndoAction } from "../src/types"

// Mock useSchedule
const mockRestoreBlocks = vi.fn()
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    restoreBlocks: mockRestoreBlocks,
  }),
}))

// Mock @inertiajs/vue3
vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn() },
}))

// We need to test composable lifecycle hooks in a component context
import { mount, config } from "@vue/test-utils"
import { defineComponent, nextTick } from "vue"
import { useUndo } from "../src/composables/useUndo"

function makeBlock(overrides: Partial<TimeBlock> = {}): TimeBlock {
  return {
    id: 1,
    title: "Test",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
    ...overrides,
  }
}

function makeAction(overrides: Partial<UndoAction> = {}): UndoAction {
  return {
    description: "Test action",
    type: "edit",
    previousBlocks: [makeBlock()],
    scheduleDate: "2026-04-10",
    ...overrides,
  }
}

// Track all mounted wrappers so afterEach can unmount them, removing
// document keydown listeners between tests to prevent cross-test interference.
const mountedWrappers: ReturnType<typeof mount>[] = []

// Helper to mount a component that uses the composable
function mountUndo(
  blocks: TimeBlock[] = [makeBlock()],
  isDisabled?: () => boolean,
) {
  let result: ReturnType<typeof useUndo> | undefined

  const Wrapper = defineComponent({
    setup() {
      result = useUndo("2026-04-10", () => blocks, isDisabled)
      return {}
    },
    render() {
      return null
    },
  })

  const wrapper = mount(Wrapper)
  mountedWrappers.push(wrapper)
  return { wrapper, undo: result! }
}

describe("useUndo", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    mountedWrappers.splice(0).forEach((w) => w.unmount())
  })

  it("pushUndo adds to stack", () => {
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "action 1" }))
    undo.pushUndo(makeAction({ description: "action 2" }))
    undo.pushUndo(makeAction({ description: "action 3" }))
    expect(undo.undoStack.value).toHaveLength(3)
    expect(undo.canUndo.value).toBe(true)
  })

  it("enforces max 20 stack size", () => {
    const { undo } = mountUndo()
    for (let i = 0; i < 25; i++) {
      undo.pushUndo(makeAction({ description: `action ${i}` }))
    }
    expect(undo.undoStack.value).toHaveLength(20)
    // Oldest (0-4) should be removed, 5 should be first
    expect(undo.undoStack.value[0].description).toBe("action 5")
  })

  it("performUndo is a no-op while schedule mutations are disabled", async () => {
    mockRestoreBlocks.mockResolvedValue({ ok: true })
    const { undo } = mountUndo([makeBlock()], () => true)
    undo.pushUndo(makeAction({ description: "blocked" }))

    await undo.performUndo()

    expect(mockRestoreBlocks).not.toHaveBeenCalled()
    expect(undo.undoStack.value).toHaveLength(1)
  })

  it("keyboard shortcut Ctrl+Z is blocked while schedule mutations are disabled", async () => {
    mockRestoreBlocks.mockResolvedValue({ ok: true })
    const { wrapper, undo } = mountUndo([makeBlock()], () => true)
    undo.pushUndo(makeAction({ description: "blocked" }))

    const event = new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true })
    document.body.dispatchEvent(event)
    await nextTick()

    expect(mockRestoreBlocks).not.toHaveBeenCalled()
    expect(undo.undoStack.value).toHaveLength(1)
  })

  it("performUndo ignores concurrent calls while restore is in flight", async () => {
    let resolveRestore: (value: { ok: boolean }) => void = () => {}
    mockRestoreBlocks.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRestore = resolve
        }),
    )
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "first" }))
    undo.pushUndo(makeAction({ description: "second" }))

    const first = undo.performUndo()
    const second = undo.performUndo()

    resolveRestore({ ok: true })
    await first
    await second

    expect(mockRestoreBlocks).toHaveBeenCalledOnce()
    expect(undo.undoStack.value).toHaveLength(1)
    expect(undo.undoStack.value[0].description).toBe("first")
  })

  it("performUndo calls restoreBlocks and pops on success", async () => {
    mockRestoreBlocks.mockResolvedValue({ ok: true })
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "first" }))
    undo.pushUndo(makeAction({ description: "second" }))

    await undo.performUndo()

    expect(mockRestoreBlocks).toHaveBeenCalledOnce()
    expect(undo.undoStack.value).toHaveLength(1)
    expect(undo.undoStack.value[0].description).toBe("first")
  })

  it("performUndo keeps action on failure", async () => {
    mockRestoreBlocks.mockResolvedValue({ ok: false, errors: { detail: "fail" } })
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "action" }))

    await undo.performUndo()

    expect(undo.undoStack.value).toHaveLength(1)
    expect(undo.currentToast.value?.description).toMatch(/failed/i)
  })

  it("performUndo on empty stack shows 'Nothing to undo' toast", async () => {
    const { undo } = mountUndo()
    await undo.performUndo()
    expect(mockRestoreBlocks).not.toHaveBeenCalled()
    expect(undo.currentToast.value?.description).toBe("Nothing to undo.")
    expect(undo.currentToast.value?.actionable).toBe(false)
  })

  it("snapshotBlocks deep clones", () => {
    const blocks = [makeBlock({ title: "Original" })]
    const { undo } = mountUndo(blocks)
    const snapshot = undo.snapshotBlocks()

    // Mutate original
    blocks[0].title = "Changed"

    expect(snapshot[0].title).toBe("Original")
  })

  it("toast auto-dismisses after 8 seconds", () => {
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "test" }))
    expect(undo.currentToast.value).not.toBeNull()

    vi.advanceTimersByTime(7999)
    expect(undo.currentToast.value).not.toBeNull()

    vi.advanceTimersByTime(1)
    expect(undo.currentToast.value).toBeNull()
  })

  it("silent action is pushed to stack but shows no toast (issue #54)", () => {
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "Added block", silent: true }))
    // No toast, but the action is still undoable.
    expect(undo.currentToast.value).toBeNull()
    expect(undo.undoStack.value).toHaveLength(1)
    expect(undo.canUndo.value).toBe(true)
  })

  it("non-silent action still shows a toast (regression)", () => {
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "AI applied", silent: false }))
    expect(undo.currentToast.value?.description).toBe("AI applied")
    expect(undo.currentToast.value?.actionable).toBe(true)
  })

  it("performUndo still toasts after a silent push (issue #54)", async () => {
    mockRestoreBlocks.mockResolvedValue({ ok: true })
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "Added block", silent: true }))
    expect(undo.currentToast.value).toBeNull()

    await undo.performUndo()
    // performUndo's own toast is independent of the action's silent flag.
    expect(undo.currentToast.value?.description).toBe("Undone: Added block")
    expect(undo.currentToast.value?.actionable).toBe(false)
  })

  it("new push clears previous toast timer", () => {
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "first" }))
    vi.advanceTimersByTime(5000)

    undo.pushUndo(makeAction({ description: "second" }))
    expect(undo.currentToast.value?.description).toBe("second")

    // After 5 more seconds (10s from first push, 5s from second) first timer
    // would have fired but was cleared
    vi.advanceTimersByTime(5000)
    expect(undo.currentToast.value).not.toBeNull()

    // Full 8s from second push
    vi.advanceTimersByTime(3000)
    expect(undo.currentToast.value).toBeNull()
  })

  it("dismissToast clears toast immediately", () => {
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({ description: "test" }))
    expect(undo.currentToast.value).not.toBeNull()

    undo.dismissToast()
    expect(undo.currentToast.value).toBeNull()
  })

  it("canUndo is false when stack is empty", () => {
    const { undo } = mountUndo()
    expect(undo.canUndo.value).toBe(false)
  })

  it("sends correct payload to restoreBlocks", async () => {
    mockRestoreBlocks.mockResolvedValue({ ok: true })
    const block = makeBlock({ id: 5, title: "Meeting", category: "personal" })
    const { undo } = mountUndo()
    undo.pushUndo(makeAction({
      previousBlocks: [block],
      scheduleDate: "2026-04-10",
    }))

    await undo.performUndo()

    expect(mockRestoreBlocks).toHaveBeenCalledWith("2026-04-10", [
      {
        title: "Meeting",
        start_time: "09:00",
        end_time: "10:00",
        category: "personal",
        is_completed: false,
        sort_order: 0,
      },
    ])
  })
})
