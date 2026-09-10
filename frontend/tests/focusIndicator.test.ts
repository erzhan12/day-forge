import { describe, expect, it } from "vitest"
import type { TimeBlock } from "../src/types"
import {
  activeUnfinishedBlock,
  isDayFinished,
  nextBlockAfter,
  pauseProgressRatio,
  pauseWindow,
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

describe("pauseWindow", () => {
  const morning = block({ id: 1, start_time: "09:00", end_time: "10:00" })
  const afternoon = block({ id: 2, start_time: "14:00", end_time: "15:00" })

  it("spans the previous block's end to the next block's start", () => {
    // 11:00 = 660, inside the 10:00–14:00 gap.
    expect(pauseWindow([morning, afternoon], 660, TODAY)).toEqual({
      startMinutes: 600,
      endMinutes: 840,
    })
  })

  it("takes the latest end among several finished blocks", () => {
    const early = block({ id: 3, start_time: "07:00", end_time: "08:00" })
    expect(pauseWindow([early, morning, afternoon], 660, TODAY)).toEqual({
      startMinutes: 600,
      endMinutes: 840,
    })
  })

  it("has a null start before the day's first block (no honest pause origin)", () => {
    expect(pauseWindow([morning], 480, TODAY)).toEqual({
      startMinutes: null,
      endMinutes: 540,
    })
  })

  it("measures from the last finished end when now sits inside a completed block", () => {
    // 09:30 inside a completed 09:00–10:00; the containing block has not ended,
    // so the pause origin is the previous block's end, not this one's.
    const completed = block({ id: 1, start_time: "09:00", end_time: "10:00", is_completed: true })
    const early = block({ id: 3, start_time: "07:00", end_time: "08:00" })
    expect(pauseWindow([early, completed, afternoon], 570, TODAY)).toEqual({
      startMinutes: 480,
      endMinutes: 840,
    })
  })

  it("treats a block ending exactly now as the pause origin", () => {
    expect(pauseWindow([morning, afternoon], 600, TODAY)).toEqual({
      startMinutes: 600,
      endMinutes: 840,
    })
  })

  it("returns null once no block starts after now (day finished)", () => {
    expect(pauseWindow([morning], 660, TODAY)).toBeNull()
  })

  it("returns null off-today or without a now signal", () => {
    expect(pauseWindow([morning, afternoon], 660, null)).toBeNull()
    expect(pauseWindow([morning, afternoon], null, TODAY)).toBeNull()
  })

  it("fails closed when any end is unparseable", () => {
    const broken = block({ id: 4, start_time: "08:00", end_time: "not-a-time" })
    expect(pauseWindow([broken, morning, afternoon], 660, TODAY)).toBeNull()
  })
})

describe("isDayFinished", () => {
  const morning = block({ id: 1, start_time: "09:00", end_time: "10:00" })

  it("is true once every block has ended", () => {
    const early = block({ id: 2, start_time: "07:00", end_time: "08:00" })
    expect(isDayFinished([early, morning], 660, TODAY)).toBe(true)
  })

  it("counts a block ending exactly now as ended", () => {
    expect(isDayFinished([morning], 600, TODAY)).toBe(true)
  })

  it("is false while any block still has time left, completed or not", () => {
    expect(isDayFinished([morning], 570, TODAY)).toBe(false)
    expect(
      isDayFinished([block({ start_time: "09:00", end_time: "10:00", is_completed: true })], 570, TODAY),
    ).toBe(false)
  })

  it("is false for an empty day — nothing was scheduled to finish", () => {
    expect(isDayFinished([], 660, TODAY)).toBe(false)
  })

  it("is false off-today or without a now signal", () => {
    expect(isDayFinished([morning], 660, null)).toBe(false)
    expect(isDayFinished([morning], null, TODAY)).toBe(false)
  })

  it("fails closed on malformed data rather than claiming a finished day", () => {
    expect(isDayFinished([block({ start_time: "bad", end_time: "10:00" })], 660, TODAY)).toBe(false)
    expect(isDayFinished([block({ start_time: "09:00", end_time: "bad" })], 660, TODAY)).toBe(false)
    // end < start: an inverted block has no meaningful "has ended".
    expect(isDayFinished([block({ start_time: "11:00", end_time: "10:00" })], 660, TODAY)).toBe(
      false,
    )
  })
})

describe("pauseProgressRatio", () => {
  // 10:00 → 14:00 pause.
  const window = { startMinutes: 600, endMinutes: 840 }

  it("returns the clamped elapsed fraction", () => {
    // 11:00 = 660, one hour into a four-hour pause.
    expect(pauseProgressRatio(window, 660)).toBeCloseTo(0.25, 10)
    expect(pauseProgressRatio(window, 720)).toBeCloseTo(0.5, 10)
  })

  it("returns 0 at the exact pause start", () => {
    expect(pauseProgressRatio(window, 600)).toBe(0)
  })

  it("clamps to [0, 1] outside the window", () => {
    expect(pauseProgressRatio(window, 500)).toBe(0)
    expect(pauseProgressRatio(window, 1_000)).toBe(1)
  })

  it("returns null when there is no measurable pause", () => {
    expect(pauseProgressRatio(null, 660)).toBeNull()
    expect(pauseProgressRatio(window, null)).toBeNull()
    // Before the day's first block: a start-less window has no origin to measure from.
    expect(pauseProgressRatio({ startMinutes: null, endMinutes: 540 }, 500)).toBeNull()
    // Zero / negative duration fails closed rather than dividing.
    expect(pauseProgressRatio({ startMinutes: 600, endMinutes: 600 }, 600)).toBeNull()
    expect(pauseProgressRatio({ startMinutes: 700, endMinutes: 600 }, 600)).toBeNull()
  })
})
