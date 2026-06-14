import { describe, expect, it } from "vitest"
import type { TimeBlock } from "../src/types"
import {
  DAY_END_MINUTES,
  DAY_START_MINUTES,
  PX_PER_MINUTE,
  STUB_MINUTES,
  buildBaseDisplayItems,
  computeRenderBounds,
  findCurrentBlock,
  formatDurationMinutes,
  formatRemainingMinutes,
  nowOffsetPercent,
  remainingMinutesForBlock,
  spliceNowMarker,
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

describe("computeRenderBounds", () => {
  it("returns full day when no visible blocks", () => {
    expect(computeRenderBounds([])).toEqual({
      renderStart: DAY_START_MINUTES,
      renderEnd: DAY_END_MINUTES,
    })
  })

  it("compresses leading gap when first block starts after stub threshold", () => {
    const bounds = computeRenderBounds([block({ start_time: "09:00", end_time: "23:00" })])
    expect(bounds.renderStart).toBe(9 * 60 - STUB_MINUTES)
    expect(bounds.renderEnd).toBe(DAY_END_MINUTES)
  })

  it("compresses trailing gap when last block ends before stub threshold", () => {
    const bounds = computeRenderBounds([block({ start_time: "06:00", end_time: "18:00" })])
    expect(bounds.renderStart).toBe(DAY_START_MINUTES)
    expect(bounds.renderEnd).toBe(18 * 60 + STUB_MINUTES)
  })

  it("compresses both edges on a mid-day schedule", () => {
    const bounds = computeRenderBounds([
      block({ id: 1, start_time: "09:00", end_time: "12:00" }),
      block({ id: 2, start_time: "13:00", end_time: "18:00", sort_order: 10 }),
    ])
    expect(bounds).toEqual({
      renderStart: 9 * 60 - STUB_MINUTES,
      renderEnd: 18 * 60 + STUB_MINUTES,
    })
  })

  it("does not compress when edge gap is at or below STUB_MINUTES", () => {
    const bounds = computeRenderBounds([
      block({ start_time: "06:30", end_time: "22:30" }),
    ])
    expect(bounds).toEqual({
      renderStart: DAY_START_MINUTES,
      renderEnd: DAY_END_MINUTES,
    })
  })

  it("keeps natural bounds when first block is at DAY_START and last at DAY_END", () => {
    const bounds = computeRenderBounds([
      block({ start_time: "06:00", end_time: "23:00" }),
    ])
    expect(bounds).toEqual({
      renderStart: DAY_START_MINUTES,
      renderEnd: DAY_END_MINUTES,
    })
  })

  it("ignores blocks entirely outside the day window", () => {
    const bounds = computeRenderBounds([
      block({ id: 1, start_time: "02:00", end_time: "05:00" }),
      block({ id: 2, start_time: "23:30", end_time: "23:59" }),
    ])
    expect(bounds).toEqual({
      renderStart: DAY_START_MINUTES,
      renderEnd: DAY_END_MINUTES,
    })
  })

  it("clamps partially outside blocks and sorts by start then sort_order", () => {
    const bounds = computeRenderBounds([
      block({ id: 2, start_time: "09:00", end_time: "22:30", sort_order: 10 }),
      block({ id: 1, start_time: "05:00", end_time: "07:00", sort_order: 0 }),
    ])
    expect(bounds).toEqual({
      renderStart: DAY_START_MINUTES,
      renderEnd: DAY_END_MINUTES,
    })
  })
})

describe("buildBaseDisplayItems drag geometry", () => {
  it("aligns leading stub height with ghost offset when preview moves later", () => {
    const liveBounds = {
      renderStart: 8 * 60 + 30,
      renderEnd: DAY_END_MINUTES,
    }
    const previewBlocks = [
      block({ id: 1, start_time: "10:00", end_time: "11:00" }),
    ]
    const items = buildBaseDisplayItems(
      previewBlocks,
      liveBounds.renderStart,
      liveBounds.renderEnd,
    )
    const leadingGap = items.find((i) => i.type === "gap")!
    expect(leadingGap.render_minutes).toBe(90)
    expect(leadingGap.compact).toBe(true)

    const cumulativePx = leadingGap.render_minutes! * PX_PER_MINUTE
    const ghostTop = (10 * 60 - liveBounds.renderStart) * PX_PER_MINUTE
    expect(cumulativePx).toBe(ghostTop)
  })

  it("aligns trailing stub height when preview last block ends earlier", () => {
    const liveBounds = {
      renderStart: DAY_START_MINUTES,
      renderEnd: 19 * 60,
    }
    const previewBlocks = [
      block({ id: 1, start_time: "09:00", end_time: "17:00" }),
    ]
    const items = buildBaseDisplayItems(
      previewBlocks,
      liveBounds.renderStart,
      liveBounds.renderEnd,
    )
    const trailingGap = items.filter((i) => i.type === "gap").pop()!
    expect(trailingGap.render_minutes).toBe(120)
    expect(trailingGap.compact).toBe(true)

    // Mirror the leading pixel-alignment assert: rendered height equals
    // (frozenRenderEnd - previewLastEnd) * PX_PER_MINUTE.
    const trailingPx = trailingGap.render_minutes! * PX_PER_MINUTE
    const expectedPx = (liveBounds.renderEnd - 17 * 60) * PX_PER_MINUTE
    expect(trailingPx).toBe(expectedPx)
  })

  // Regression for P2: compactness must follow the active/frozen bounds, not a
  // separate live value. A mid-drag live mutation could make live bounds
  // natural while frozen bounds stay compressed — the gap must keep compacting.
  it("derives leading compactness from active bounds, ignoring block geometry", () => {
    // Active/frozen bounds natural even though the (preview) first block is
    // 09:00 — the leading gap must NOT compact.
    const naturalActive = buildBaseDisplayItems(
      [block({ start_time: "09:00", end_time: "18:00" })],
      DAY_START_MINUTES,
      DAY_END_MINUTES,
    )
    const leadingNatural = naturalActive.find((i) => i.type === "gap")!
    expect(leadingNatural.compact).toBeUndefined()
    expect(leadingNatural.render_minutes).toBeUndefined()
    expect(leadingNatural.duration_minutes).toBe(180)

    // Active/frozen bounds compressed — the leading gap must compact and use
    // render_minutes anchored at the frozen origin.
    const compressedActive = buildBaseDisplayItems(
      [block({ start_time: "09:00", end_time: "18:00" })],
      9 * 60 - STUB_MINUTES,
      DAY_END_MINUTES,
    )
    const leadingCompressed = compressedActive.find((i) => i.type === "gap")!
    expect(leadingCompressed.compact).toBe(true)
    expect(leadingCompressed.render_minutes).toBe(STUB_MINUTES)
  })

  it("derives trailing compactness from active bounds, ignoring block geometry", () => {
    const naturalActive = buildBaseDisplayItems(
      [block({ start_time: "06:00", end_time: "18:00" })],
      DAY_START_MINUTES,
      DAY_END_MINUTES,
    )
    const trailingNatural = naturalActive.filter((i) => i.type === "gap").pop()!
    expect(trailingNatural.compact).toBeUndefined()
    expect(trailingNatural.render_minutes).toBeUndefined()
    expect(trailingNatural.duration_minutes).toBe(300)

    const compressedActive = buildBaseDisplayItems(
      [block({ start_time: "06:00", end_time: "18:00" })],
      DAY_START_MINUTES,
      18 * 60 + STUB_MINUTES,
    )
    const trailingCompressed = compressedActive
      .filter((i) => i.type === "gap")
      .pop()!
    expect(trailingCompressed.compact).toBe(true)
    expect(trailingCompressed.render_minutes).toBe(STUB_MINUTES)
  })
})

describe("spliceNowMarker", () => {
  it("returns the list unchanged when off-today (null date or null now)", () => {
    const items = buildBaseDisplayItems(
      [block({ start_time: "09:00", end_time: "18:00" })],
      9 * 60 - STUB_MINUTES,
      DAY_END_MINUTES,
    )
    expect(spliceNowMarker(items, 7 * 60, null)).toBe(items)
    expect(spliceNowMarker(items, null, "2026-06-14")).toBe(items)
  })

  it("converts a compact edge gap to gap-with-now, preserving render_minutes and compact", () => {
    const items = buildBaseDisplayItems(
      [block({ start_time: "09:00", end_time: "18:00" })],
      9 * 60 - STUB_MINUTES, // active/frozen compressed → leading stub
      DAY_END_MINUTES,
    )
    const leading = items[0]
    expect(leading.type).toBe("gap")
    expect(leading.compact).toBe(true)
    expect(leading.render_minutes).toBe(STUB_MINUTES)

    // now at 07:30 falls inside the 06:00–09:00 leading stub
    const spliced = spliceNowMarker(items, 7 * 60 + 30, "2026-06-14")
    const nowItem = spliced[0]
    expect(nowItem.type).toBe("gap-with-now")
    expect(nowItem.compact).toBe(true)
    expect(nowItem.render_minutes).toBe(STUB_MINUTES)
    // semantic range survives the splice, so the now-offset stays proportional
    expect(
      nowOffsetPercent(nowItem.start_time, nowItem.end_time, 7 * 60 + 30),
    ).toBe("50%")
  })

  it("converts a block to block-with-now and marks only the first match", () => {
    const items = buildBaseDisplayItems(
      [
        block({ id: 1, start_time: "09:00", end_time: "10:00" }),
        block({ id: 2, start_time: "11:00", end_time: "12:00", sort_order: 10 }),
      ],
      DAY_START_MINUTES,
      DAY_END_MINUTES,
    )
    const spliced = spliceNowMarker(items, 9 * 60 + 30, "2026-06-14")
    const withNow = spliced.filter((i) => i.type.endsWith("-with-now"))
    expect(withNow).toHaveLength(1)
    expect(withNow[0].type).toBe("block-with-now")
    expect(withNow[0].block?.id).toBe(1)
  })
})

describe("nowOffsetPercent", () => {
  it("returns 0% when now is unknown (off-today)", () => {
    expect(nowOffsetPercent("06:00", "09:00", null)).toBe("0%")
  })

  it("positions now proportionally within a compact stub's semantic range", () => {
    // 06:00–09:00 stub, now at 07:30 → midpoint → 50% (mapped onto the
    // compressed render height by CSS).
    expect(nowOffsetPercent("06:00", "09:00", 7 * 60 + 30)).toBe("50%")
  })

  it("clamps a zero or negative span to 0%", () => {
    expect(nowOffsetPercent("09:00", "09:00", 9 * 60)).toBe("0%")
  })
})

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
