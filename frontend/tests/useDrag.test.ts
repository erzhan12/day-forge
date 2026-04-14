import { describe, it, expect } from "vitest"
import { resolveConflicts } from "../src/composables/useDrag"
import type { TimeBlock } from "../src/types"

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
