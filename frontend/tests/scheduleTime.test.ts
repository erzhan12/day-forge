import { describe, expect, it } from "vitest"
import type { TimeBlock } from "../src/types"
import {
  findCurrentBlock,
  formatDurationMinutes,
  formatRemainingMinutes,
  remainingMinutesForBlock,
} from "../src/utils/scheduleTime"

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

describe("scheduleTime current-block helpers", () => {
  it("returns null when nowDate is null", () => {
    expect(findCurrentBlock([block()], 9 * 60 + 30, null)).toBeNull()
  })

  it("returns the block containing now", () => {
    const current = block({ id: 2, start_time: "10:00", end_time: "11:00" })
    expect(
      findCurrentBlock(
        [
          block({ id: 1, start_time: "09:00", end_time: "10:00" }),
          current,
        ],
        10 * 60 + 30,
        "2026-05-22",
      ),
    ).toBe(current)
  })

  it("returns null before blocks, in a gap, and at the end-exclusive boundary", () => {
    const blocks = [
      block({ id: 1, start_time: "09:00", end_time: "10:00" }),
      block({ id: 2, start_time: "11:00", end_time: "12:00" }),
    ]

    expect(findCurrentBlock(blocks, 8 * 60 + 59, "2026-05-22")).toBeNull()
    expect(findCurrentBlock(blocks, 10 * 60 + 30, "2026-05-22")).toBeNull()
    expect(findCurrentBlock(blocks, 10 * 60, "2026-05-22")).toBeNull()
  })

  it("uses start time then sort order when overlapping blocks contain now", () => {
    const later = block({ id: 1, start_time: "09:30", end_time: "10:30", sort_order: 0 })
    const first = block({ id: 2, start_time: "09:00", end_time: "10:00", sort_order: 2 })
    const second = block({ id: 3, start_time: "09:00", end_time: "10:00", sort_order: 3 })

    expect(
      findCurrentBlock([second, later, first], 9 * 60 + 45, "2026-05-22"),
    ).toBe(first)
  })

  it("returns clamped remaining minutes only inside the block window", () => {
    const current = block({ start_time: "09:00", end_time: "10:00" })

    expect(remainingMinutesForBlock(current, 9 * 60 + 37)).toBe(23)
    expect(remainingMinutesForBlock(current, 10 * 60)).toBeNull()
    expect(remainingMinutesForBlock(current, 8 * 60 + 59)).toBeNull()
  })
})

describe("scheduleTime duration formatters", () => {
  it.each([
    [-5, "0m"],
    [0, "0m"],
    [23, "23m"],
    [59, "59m"],
    [60, "1h"],
    [90, "1h 30m"],
    [120, "2h"],
    [1440, "24h"],
  ])("formats %i minutes as %s", (minutes, expected) => {
    expect(formatDurationMinutes(minutes)).toBe(expected)
  })

  it.each([
    [23, "23m left"],
    [60, "1h left"],
    [90, "1h 30m left"],
  ])("formats %i remaining minutes as %s", (minutes, expected) => {
    expect(formatRemainingMinutes(minutes)).toBe(expected)
  })
})
