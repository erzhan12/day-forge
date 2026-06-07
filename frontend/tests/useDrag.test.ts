import { describe, it, expect, vi } from "vitest"
import { blocksExternallyMutated, resolveConflicts, useDrag } from "../src/composables/useDrag"
import type { TimeBlock, UndoAction } from "../src/types"

function makeBlock(overrides: Partial<TimeBlock> & { id: number }): TimeBlock {
  return {
    title: `Block ${overrides.id}`,
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
    ...overrides,
  }
}

describe("resolveConflicts", () => {
  it("no shift when no overlap", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
      makeBlock({ id: 2, start_time: "10:00", end_time: "11:00", sort_order: 10 }),
    ]
    // Move block 1 to 09:00-10:00 (no overlap with block 2)
    const result = resolveConflicts(blocks, 1, 540, 600)
    expect(result).not.toBeNull()
    expect(result!.find((b) => b.id === 1)!.start_time).toBe("09:00")
    expect(result!.find((b) => b.id === 2)!.start_time).toBe("10:00")
  })

  it("single block shifts forward on overlap", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
      makeBlock({ id: 2, start_time: "10:00", end_time: "11:00", sort_order: 10 }),
    ]
    // Move block 1 to 09:30-10:30 (overlaps with block 2 at 10:00-11:00)
    const result = resolveConflicts(blocks, 1, 570, 630)
    expect(result).not.toBeNull()
    expect(result!.find((b) => b.id === 1)!.start_time).toBe("09:30")
    expect(result!.find((b) => b.id === 1)!.end_time).toBe("10:30")
    // Block 2 should shift to start after 10:30
    expect(result!.find((b) => b.id === 2)!.start_time).toBe("10:30")
    expect(result!.find((b) => b.id === 2)!.end_time).toBe("11:30")
  })

  it("cascade through multiple blocks", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
      makeBlock({ id: 2, start_time: "10:00", end_time: "10:30", sort_order: 10 }),
      makeBlock({ id: 3, start_time: "10:30", end_time: "11:00", sort_order: 20 }),
      makeBlock({ id: 4, start_time: "11:00", end_time: "11:30", sort_order: 30 }),
    ]
    // Move block 1 to 10:00-11:00 (overlaps blocks 2, 3, and causes cascade to 4)
    const result = resolveConflicts(blocks, 1, 600, 660)
    expect(result).not.toBeNull()
    expect(result!.find((b) => b.id === 1)!.start_time).toBe("10:00")
    expect(result!.find((b) => b.id === 1)!.end_time).toBe("11:00")
    expect(result!.find((b) => b.id === 2)!.start_time).toBe("11:00")
    expect(result!.find((b) => b.id === 2)!.end_time).toBe("11:30")
    expect(result!.find((b) => b.id === 3)!.start_time).toBe("11:30")
    expect(result!.find((b) => b.id === 3)!.end_time).toBe("12:00")
    expect(result!.find((b) => b.id === 4)!.start_time).toBe("12:00")
    expect(result!.find((b) => b.id === 4)!.end_time).toBe("12:30")
  })

  it("returns null when cascade exceeds DAY_END", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
      makeBlock({ id: 2, start_time: "22:00", end_time: "23:00", sort_order: 10 }),
    ]
    // Move block 1 to overlap block 2. Block 2 (1h) would shift to 23:00-24:00 → exceeds DAY_END (23:00)
    const result = resolveConflicts(blocks, 1, 1320, 1380) // 22:00-23:00
    expect(result).toBeNull()
  })

  it("handles dragging block to earlier time", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
      makeBlock({ id: 2, start_time: "10:00", end_time: "11:00", sort_order: 10 }),
    ]
    // Move block 2 to 07:00-08:00 (no overlap)
    const result = resolveConflicts(blocks, 2, 420, 480)
    expect(result).not.toBeNull()
    expect(result!.find((b) => b.id === 2)!.start_time).toBe("07:00")
    expect(result!.find((b) => b.id === 2)!.end_time).toBe("08:00")
    // Block 1 unchanged
    expect(result!.find((b) => b.id === 1)!.start_time).toBe("08:00")
  })

  it("reassigns sort_order after resolution", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 100 }),
      makeBlock({ id: 2, start_time: "10:00", end_time: "11:00", sort_order: 200 }),
    ]
    const result = resolveConflicts(blocks, 1, 480, 540) // no-op move
    expect(result).not.toBeNull()
    expect(result![0].sort_order).toBe(0)
    expect(result![1].sort_order).toBe(10)
  })

  it("no-op move returns blocks with updated sort_order only", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
    ]
    // Move to same position
    const result = resolveConflicts(blocks, 1, 480, 540)
    expect(result).not.toBeNull()
    expect(result!).toHaveLength(1)
    expect(result![0].start_time).toBe("08:00")
    expect(result![0].end_time).toBe("09:00")
  })

  it("anchors dragged block when dropped onto an earlier block", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
      makeBlock({ id: 2, start_time: "10:00", end_time: "11:00", sort_order: 10 }),
    ]
    // Drag block 2 upward to 08:30-09:30 (overlaps block 1 at 08:00-09:00)
    const result = resolveConflicts(blocks, 2, 510, 570)
    expect(result).not.toBeNull()
    // Dragged block must stay at the drop position
    expect(result!.find((b) => b.id === 2)!.start_time).toBe("08:30")
    expect(result!.find((b) => b.id === 2)!.end_time).toBe("09:30")
    // The earlier block (1) should shift forward past the dragged block
    expect(result!.find((b) => b.id === 1)!.start_time).toBe("09:30")
    expect(result!.find((b) => b.id === 1)!.end_time).toBe("10:30")
  })

  it("handles adjacent blocks without shifting", () => {
    const blocks = [
      makeBlock({ id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 }),
      makeBlock({ id: 2, start_time: "09:00", end_time: "10:00", sort_order: 10 }),
    ]
    // Move block 1 to 08:00-09:00 (exactly adjacent, no overlap)
    const result = resolveConflicts(blocks, 1, 480, 540)
    expect(result).not.toBeNull()
    // Block 2 should not shift
    expect(result!.find((b) => b.id === 2)!.start_time).toBe("09:00")
    expect(result!.find((b) => b.id === 2)!.end_time).toBe("10:00")
  })

  it("resolves a 30-block full-day cascade well under the iteration cap", () => {
    // Realistic worst case: 30 back-to-back 10-minute blocks filling
    // 06:00 – 11:00. Dragging the first block forward by 10 minutes
    // forces every subsequent block to shift forward once — a full-tail
    // cascade that exercises the while/re-sort loop the hardest a real
    // schedule can. We can't observe the internal iteration counter
    // without polluting the public API, so we assert the result is
    // non-null (if MAX_ITERATIONS=1000 were hit the function would
    // return null) and that the tail blocks land at the expected
    // positions. Complete, correct output proves the loop converged in
    // at most ~30 shifts — two orders of magnitude below the cap.
    //
    // Also guards performance: a regression that blew up the iteration
    // count would surface here long before hitting MAX_ITERATIONS.
    const blocks: TimeBlock[] = []
    for (let i = 0; i < 30; i++) {
      const startMin = 360 + i * 10 // 06:00 + i*10min
      const hh = Math.floor(startMin / 60)
      const mm = startMin % 60
      const pad = (n: number) => n.toString().padStart(2, "0")
      const endMin = startMin + 10
      const eh = Math.floor(endMin / 60)
      const em = endMin % 60
      blocks.push(
        makeBlock({
          id: i + 1,
          start_time: `${pad(hh)}:${pad(mm)}`,
          end_time: `${pad(eh)}:${pad(em)}`,
          sort_order: i * 10,
        }),
      )
    }

    // Drag block 1 from 06:00-06:10 to 06:10-06:20 — overlaps block 2,
    // which must cascade through blocks 3..30 (each shifts +10 min).
    const start = performance.now()
    const result = resolveConflicts(blocks, 1, 370, 380)
    const elapsedMs = performance.now() - start

    expect(result).not.toBeNull()
    expect(result!).toHaveLength(30)

    // Dragged block anchored at its drop position.
    const b1 = result!.find((b) => b.id === 1)!
    expect(b1.start_time).toBe("06:10")
    expect(b1.end_time).toBe("06:20")

    // Blocks 2..30 each shifted forward by exactly 10 minutes, so block k
    // (1-indexed from 2) now starts at 06:00 + k*10 min. Last block (30)
    // lands at 11:00-11:10.
    const b30 = result!.find((b) => b.id === 30)!
    expect(b30.start_time).toBe("11:00")
    expect(b30.end_time).toBe("11:10")

    // Loose upper bound to catch runaway regressions. A correct
    // cascade finishes in single-digit milliseconds on modern hardware,
    // and MAX_ITERATIONS=1000 would take far longer than 500ms even in
    // slow CI. Keeping this generous so it doesn't flake.
    expect(elapsedMs).toBeLessThan(500)
  })
})

/**
 * Mount-style harness for `useDrag.endDrag()`. Builds enough of a fake
 * pointer event + container element to satisfy `startDrag`'s DOM
 * dependencies (setPointerCapture, getBoundingClientRect, addEventListener),
 * then lets the test populate `previewBlocks` directly to simulate the
 * drag move before calling `endDrag()`.
 */
function makeFakeContainer() {
  // Real DOM element so jsdom APIs like getComputedStyle work; method
  // stubs replace the pointer/listener calls the drag code makes.
  const el = document.createElement("div")
  el.setPointerCapture = vi.fn()
  el.releasePointerCapture = vi.fn()
  el.addEventListener = vi.fn() as unknown as typeof el.addEventListener
  el.removeEventListener = vi.fn() as unknown as typeof el.removeEventListener
  el.getBoundingClientRect = () =>
    ({
      top: 0, left: 0, right: 0, bottom: 0,
      width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}),
    }) as DOMRect
  return el
}

describe("useDrag.endDrag (undo snapshot)", () => {
  it("pushes pre-drag blocks (not [], not the post-reset snapshot) into the undo action", async () => {
    // Regression test for the snapshot-after-resetState bug:
    //   - resetState() clears the module-scoped `snapshot` to []
    //   - endDrag() then awaits reorderBlocks before calling pushUndo
    //   - reading `snapshot` after the await captured [] (or, on a fast
    //     second drag, that drag's snapshot), so undoing a drag would
    //     restore the schedule to an empty day.
    // The fix captures the snapshot into a local const before resetState.
    const original: TimeBlock[] = [
      { id: 1, title: "A", start_time: "09:00", end_time: "10:00",
        category: "work", is_completed: false, sort_order: 0 },
      { id: 2, title: "B", start_time: "10:00", end_time: "11:00",
        category: "work", is_completed: false, sort_order: 10 },
    ]
    // snapshotBlocks must return a fresh deep copy each call (mirrors the
    // structuredClone behaviour in useUndo.snapshotBlocks).
    const snapshotBlocks = vi.fn(() =>
      original.map((b) => ({ ...b })),
    )
    const getCurrentBlocks = vi.fn(() => original)
    const reorderBlocks = vi.fn(async () => ({ ok: true as const }))
    const pushUndo = vi.fn<(a: UndoAction) => void>()

    const drag = useDrag(
      "2026-04-16",
      getCurrentBlocks,
      reorderBlocks,
      pushUndo,
      snapshotBlocks,
    )

    const container = makeFakeContainer()
    const event = { pointerId: 1, clientY: 0 } as PointerEvent
    drag.startDrag(event, original[0], container)

    // Simulate the pointer-move outcome: block 1 lands at 11:00-12:00,
    // block 2 stays put. previewBlocks differs from snapshot, so the
    // updates array is non-empty and reorderBlocks will be called.
    drag.previewBlocks.value = [
      { ...original[1] },
      { ...original[0], start_time: "11:00", end_time: "12:00" },
    ]
    drag.previewStartTime.value = "11:00"

    await drag.endDrag()

    expect(reorderBlocks).toHaveBeenCalledOnce()
    expect(pushUndo).toHaveBeenCalledOnce()
    const action = pushUndo.mock.calls[0][0]
    expect(action.type).toBe("drag")
    expect(action.scheduleDate).toBe("2026-04-16")
    // Critical: previousBlocks must hold the pre-drag state, not [] and
    // not the post-resetState snapshot.
    expect(action.previousBlocks).toHaveLength(2)
    expect(action.previousBlocks.map((b) => b.id).sort()).toEqual([1, 2])
    const a = action.previousBlocks.find((b) => b.id === 1)!
    expect(a.start_time).toBe("09:00")
    expect(a.end_time).toBe("10:00")
  })

  it("uses the latest date source when pushing drag undo", async () => {
    const original: TimeBlock[] = [
      { id: 1, title: "A", start_time: "09:00", end_time: "10:00",
        category: "work", is_completed: false, sort_order: 0 },
    ]
    const snapshotBlocks = vi.fn(() => original.map((b) => ({ ...b })))
    const getCurrentBlocks = vi.fn(() => original)
    const reorderBlocks = vi.fn(async () => ({ ok: true as const }))
    const pushUndo = vi.fn<(a: UndoAction) => void>()
    let currentDate = "2026-04-16"

    const drag = useDrag(
      () => currentDate,
      getCurrentBlocks,
      reorderBlocks,
      pushUndo,
      snapshotBlocks,
    )
    currentDate = "2026-04-17"

    drag.startDrag(
      { pointerId: 1, clientY: 0 } as PointerEvent,
      original[0],
      makeFakeContainer(),
    )
    drag.previewBlocks.value = [
      { ...original[0], start_time: "11:00", end_time: "12:00" },
    ]
    drag.previewStartTime.value = "11:00"

    await drag.endDrag()

    expect(pushUndo).toHaveBeenCalledOnce()
    expect(pushUndo.mock.calls[0][0].scheduleDate).toBe("2026-04-17")
  })

  it("binds drag undo to the date that was active at drag start, not at drop", async () => {
    // Regression: pointer capture blocks date nav during the drag itself,
    // but cleanup() releases the pointer before `await reorderBlocks`.
    // During that await the user can navigate dates — and the undo must
    // still target the day the drag actually mutated, not the day the
    // user happens to be looking at when pushUndo fires.
    const original: TimeBlock[] = [
      { id: 1, title: "A", start_time: "09:00", end_time: "10:00",
        category: "work", is_completed: false, sort_order: 0 },
    ]
    const snapshotBlocks = vi.fn(() => original.map((b) => ({ ...b })))
    const getCurrentBlocks = vi.fn(() => original)
    const reorderBlocks = vi.fn(async () => ({ ok: true as const }))
    const pushUndo = vi.fn<(a: UndoAction) => void>()
    let currentDate = "2026-04-16"

    const drag = useDrag(
      () => currentDate,
      getCurrentBlocks,
      reorderBlocks,
      pushUndo,
      snapshotBlocks,
    )

    drag.startDrag(
      { pointerId: 1, clientY: 0 } as PointerEvent,
      original[0],
      makeFakeContainer(),
    )
    // Simulate the user navigating to a different day between drag start
    // and pushUndo (the window opened by `await reorderBlocks`).
    currentDate = "2026-04-17"
    drag.previewBlocks.value = [
      { ...original[0], start_time: "11:00", end_time: "12:00" },
    ]
    drag.previewStartTime.value = "11:00"

    await drag.endDrag()

    expect(pushUndo).toHaveBeenCalledOnce()
    expect(pushUndo.mock.calls[0][0].scheduleDate).toBe("2026-04-16")
  })

  it("first drag's undo keeps its own snapshot when a second drag starts mid-await", async () => {
    // Race version of the same bug. While drag 1's reorderBlocks promise
    // is in-flight, the user starts drag 2 — startDrag would overwrite
    // the module-scoped `snapshot`. Without the local capture, drag 1's
    // pushUndo would then reference drag 2's snapshot.
    const day1: TimeBlock[] = [
      { id: 1, title: "A", start_time: "09:00", end_time: "10:00",
        category: "work", is_completed: false, sort_order: 0 },
      { id: 2, title: "B", start_time: "10:00", end_time: "11:00",
        category: "work", is_completed: false, sort_order: 10 },
    ]
    // After drag 1 commits, the day looks different — startDrag for
    // drag 2 will snapshot this newer state.
    const day2: TimeBlock[] = [
      { id: 1, title: "A", start_time: "11:00", end_time: "12:00",
        category: "work", is_completed: false, sort_order: 10 },
      { id: 2, title: "B", start_time: "10:00", end_time: "11:00",
        category: "work", is_completed: false, sort_order: 0 },
    ]
    let phase: "drag1" | "drag2" = "drag1"
    const snapshotBlocks = vi.fn(() =>
      (phase === "drag1" ? day1 : day2).map((b) => ({ ...b })),
    )
    const getCurrentBlocks = vi.fn(() =>
      phase === "drag1" ? day1 : day2,
    )

    // Hold drag 1's reorder promise open so we can start drag 2 in the
    // gap. Resolve it manually after drag 2's startDrag fires.
    let resolveReorder1!: (v: { ok: true }) => void
    const reorder1 = new Promise<{ ok: true }>((r) => {
      resolveReorder1 = r
    })
    const reorderBlocks = vi
      .fn<(...args: unknown[]) => Promise<{ ok: true }>>()
      .mockImplementationOnce(() => reorder1)
      .mockResolvedValue({ ok: true })

    const pushUndo = vi.fn<(a: UndoAction) => void>()

    const drag = useDrag(
      "2026-04-16",
      getCurrentBlocks,
      reorderBlocks,
      pushUndo,
      snapshotBlocks,
    )
    const container = makeFakeContainer()

    // Drag 1: A moves from 09:00-10:00 → 11:00-12:00.
    drag.startDrag({ pointerId: 1, clientY: 0 } as PointerEvent, day1[0], container)
    drag.previewBlocks.value = [
      { ...day1[1] },
      { ...day1[0], start_time: "11:00", end_time: "12:00" },
    ]
    drag.previewStartTime.value = "11:00"
    const end1 = drag.endDrag() // do not await — leaves reorder1 pending

    // Drag 2 starts before drag 1's API call resolves. This is the
    // exact window in which a stray module-scoped `snapshot` write would
    // clobber drag 1's pending undo.
    phase = "drag2"
    drag.startDrag({ pointerId: 2, clientY: 0 } as PointerEvent, day2[1], container)
    drag.previewBlocks.value = [
      { ...day2[1], start_time: "12:00", end_time: "13:00" },
    ]
    drag.previewStartTime.value = "12:00"

    // Now let drag 1 finish.
    resolveReorder1({ ok: true })
    await end1

    expect(pushUndo).toHaveBeenCalledOnce()
    const action = pushUndo.mock.calls[0][0]
    // Drag 1's undo must restore day1 (block A at 09:00-10:00), NOT day2.
    const a = action.previousBlocks.find((b) => b.id === 1)!
    expect(a.start_time).toBe("09:00")
    expect(a.end_time).toBe("10:00")
  })

  it("aborts drop when a non-dragged block changed during the drag", async () => {
    const snapshot: TimeBlock[] = [
      { id: 1, title: "A", start_time: "09:00", end_time: "10:00",
        category: "work", is_completed: false, sort_order: 0 },
      { id: 2, title: "B", start_time: "10:00", end_time: "11:00",
        category: "work", is_completed: false, sort_order: 10 },
    ]
    const liveAfterAi: TimeBlock[] = [
      { ...snapshot[0] },
      { ...snapshot[1], start_time: "14:00", end_time: "15:00" },
    ]
    const snapshotBlocks = vi.fn(() => snapshot.map((b) => ({ ...b })))
    const getCurrentBlocks = vi.fn(() => liveAfterAi)
    const reorderBlocks = vi.fn(async () => ({ ok: true as const }))
    const pushUndo = vi.fn<(a: UndoAction) => void>()

    const drag = useDrag(
      "2026-04-16",
      getCurrentBlocks,
      reorderBlocks,
      pushUndo,
      snapshotBlocks,
    )

    drag.startDrag(
      { pointerId: 1, clientY: 0 } as PointerEvent,
      snapshot[0],
      makeFakeContainer(),
    )
    drag.previewBlocks.value = [
      { ...snapshot[0], start_time: "11:00", end_time: "12:00" },
      liveAfterAi[1],
    ]
    drag.previewStartTime.value = "11:00"

    await drag.endDrag()

    expect(reorderBlocks).not.toHaveBeenCalled()
    expect(pushUndo).not.toHaveBeenCalled()
  })
})

describe("blocksExternallyMutated", () => {
  const snapshot: TimeBlock[] = [
    { id: 1, title: "A", start_time: "09:00", end_time: "10:00",
      category: "work", is_completed: false, sort_order: 0 },
    { id: 2, title: "B", start_time: "10:00", end_time: "11:00",
      category: "work", is_completed: false, sort_order: 10 },
  ]

  it("returns false when only the dragged block may change", () => {
    expect(blocksExternallyMutated(snapshot, snapshot, 1)).toBe(false)
  })

  it("returns true when a neighbour's times changed", () => {
    const live = [
      snapshot[0],
      { ...snapshot[1], start_time: "14:00", end_time: "15:00" },
    ]
    expect(blocksExternallyMutated(snapshot, live, 1)).toBe(true)
  })

  it("returns true when a neighbour's sort_order changed", () => {
    const live = [
      snapshot[0],
      { ...snapshot[1], sort_order: 99 },
    ]
    expect(blocksExternallyMutated(snapshot, live, 1)).toBe(true)
  })

  it("returns false when the dragged block itself changed", () => {
    const live = [
      { ...snapshot[0], start_time: "11:00", end_time: "12:00" },
      snapshot[1],
    ]
    expect(blocksExternallyMutated(snapshot, live, 1)).toBe(false)
  })

  it("returns true when block ids differ", () => {
    expect(blocksExternallyMutated(snapshot, [snapshot[0]], 1)).toBe(true)
  })
})
