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
})
