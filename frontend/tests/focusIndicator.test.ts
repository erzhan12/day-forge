import { describe, expect, it } from "vitest"
import type { TimeBlock } from "../src/types"
import {
  activeUnfinishedBlock,
  nextBlockAfter,
  progressRatio,
  progressPercentFromRatio,
} from "../src/utils/focusIndicator"

function block(overrides: Partial<TimeBlock> = {}): TimeBlock {
  return {
    id: 1,
    title: "Block",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
    ...overrides,
  }
}

const TODAY = "2026-08-12"

describe("activeUnfinishedBlock", () => {
  it("returns the findCurrentBlock winner when it is not completed", () => {
    const b = block({ start_time: "09:00", end_time: "10:00", is_completed: false })
    // 09:30 = 570 minutes, inside [540, 600)
    expect(activeUnfinishedBlock([b], 570, TODAY)).toBe(b)
  })

  it("returns null when the current block is completed", () => {
    const b = block({ start_time: "09:00", end_time: "10:00", is_completed: true })
    expect(activeUnfinishedBlock([b], 570, TODAY)).toBeNull()
  })

  it("returns null in a gap (no block contains now)", () => {
    const b = block({ start_time: "09:00", end_time: "10:00" })
    // 11:00 = 660, after the block
    expect(activeUnfinishedBlock([b], 660, TODAY)).toBeNull()
  })

  it("returns null when nowMinutes is null, short-circuiting before findCurrentBlock", () => {
    const b = block({ start_time: "00:00", end_time: "23:59" })
    // With a raw pass-through, null coerces to 0 and would match a 00:00 block.
    // The guard must return null first.
    expect(activeUnfinishedBlock([b], null, TODAY)).toBeNull()
  })

  it("returns null when nowDate is null (off-today)", () => {
    const b = block({ start_time: "09:00", end_time: "10:00" })
    expect(activeUnfinishedBlock([b], 570, null)).toBeNull()
  })

  it("returns the overlap winner (earliest start, then sort_order), gated on completion", () => {
    const early = block({ id: 1, start_time: "09:00", end_time: "10:00", sort_order: 5 })
    const later = block({ id: 2, start_time: "09:30", end_time: "10:30", sort_order: 0 })
    // 09:45 = 585 inside both; earliest start (09:00) wins
    expect(activeUnfinishedBlock([later, early], 585, TODAY)).toBe(early)
  })

  it("resolves same-start overlap by sort_order", () => {
    const a = block({ id: 1, start_time: "09:00", end_time: "10:00", sort_order: 2 })
    const b = block({ id: 2, start_time: "09:00", end_time: "10:00", sort_order: 1 })
    expect(activeUnfinishedBlock([a, b], 570, TODAY)).toBe(b)
  })
})

describe("nextBlockAfter", () => {
  it("returns the nearest strictly later block from unsorted input without mutating it", () => {
    const later = block({ id: 3, start_time: "13:00", end_time: "14:00" })
    const nearest = block({ id: 2, start_time: "11:00", end_time: "12:00" })
    const past = block({ id: 1, start_time: "09:00", end_time: "10:00" })
    const blocks = [later, past, nearest]
    expect(nextBlockAfter(blocks, 600, TODAY)).toBe(nearest)
    expect(blocks).toEqual([later, past, nearest])
  })

  it("breaks equal starts by sort_order and includes completed future blocks", () => {
    const first = block({ id: 1, start_time: "11:00", end_time: "12:00", sort_order: 1, is_completed: true })
    const second = block({ id: 2, start_time: "11:00", end_time: "12:00", sort_order: 2 })
    expect(nextBlockAfter([second, first], 600, TODAY)).toBe(first)
  })

  it("does not treat a completed block containing now as next", () => {
    const current = block({ id: 1, start_time: "09:00", end_time: "10:00", is_completed: true })
    const later = block({ id: 2, start_time: "11:00", end_time: "12:00" })
    expect(nextBlockAfter([current, later], 570, TODAY)).toBe(later)
  })

  it("excludes a block that starts exactly now and returns null after the final start", () => {
    const b = block({ start_time: "10:00", end_time: "11:00" })
    expect(nextBlockAfter([b], 600, TODAY)).toBeNull()
    expect(nextBlockAfter([b], 700, TODAY)).toBeNull()
  })

  it("returns null for empty data or a missing today signal", () => {
    expect(nextBlockAfter([], 600, TODAY)).toBeNull()
    expect(nextBlockAfter([block()], null, TODAY)).toBeNull()
    expect(nextBlockAfter([block()], 600, null)).toBeNull()
  })

  it("fails closed when any start is unparseable, even for an irrelevant past block", () => {
    const malformedPast = block({ id: 1, start_time: "bad", end_time: "10:00" })
    const future = block({ id: 2, start_time: "11:00", end_time: "12:00" })
    expect(nextBlockAfter([malformedPast, future], 600, TODAY)).toBeNull()
  })

  it.each([
    ["unparseable", "11:00", "bad"],
    ["zero duration", "11:00", "11:00"],
    ["negative duration", "11:00", "10:00"],
  ])("fails closed for a selected future block with %s duration", (_name, start_time, end_time) => {
    const invalid = block({ id: 1, start_time, end_time, sort_order: 0 })
    const laterValid = block({ id: 2, start_time: "12:00", end_time: "13:00" })
    expect(nextBlockAfter([laterValid, invalid], 600, TODAY)).toBeNull()
  })

  it("does not skip an invalid equal-start sibling to a valid one", () => {
    const invalid = block({ id: 1, start_time: "11:00", end_time: "11:00", sort_order: 0 })
    const valid = block({ id: 2, start_time: "11:00", end_time: "12:00", sort_order: 1 })
    expect(nextBlockAfter([valid, invalid], 600, TODAY)).toBeNull()
  })
})

describe("progressRatio", () => {
  it("returns a clamped 0..1 ratio at mid-block", () => {
    const b = block({ start_time: "09:00", end_time: "10:00" })
    // 09:30 = 570; (570-540)/60 = 0.5
    expect(progressRatio(b, 570)).toBeCloseTo(0.5, 5)
  })

  it("returns 0 at the exact start minute", () => {
    const b = block({ start_time: "09:00", end_time: "10:00" })
    expect(progressRatio(b, 540)).toBe(0)
  })

  it("clamps below 0 to 0 and above duration to 1", () => {
    const b = block({ start_time: "09:00", end_time: "10:00" })
    expect(progressRatio(b, 500)).toBe(0)
    expect(progressRatio(b, 900)).toBe(1)
  })

  it("returns null for zero duration (fail closed to neutral)", () => {
    const b = block({ start_time: "09:00", end_time: "09:00" })
    expect(progressRatio(b, 540)).toBeNull()
  })

  it("returns null for negative duration", () => {
    const b = block({ start_time: "10:00", end_time: "09:00" })
    expect(progressRatio(b, 570)).toBeNull()
  })

  it("returns null for a NaN duration (unparseable time)", () => {
    const b = block({ start_time: "not-a-time", end_time: "10:00" })
    expect(progressRatio(b, 570)).toBeNull()
  })
})

describe("progressPercentFromRatio", () => {
  it("rounds a ratio to an integer percent", () => {
    expect(progressPercentFromRatio(0.5)).toBe(50)
    expect(progressPercentFromRatio(0.336)).toBe(34)
  })

  it("returns 0 for a null (neutral) ratio", () => {
    expect(progressPercentFromRatio(null)).toBe(0)
  })
})
