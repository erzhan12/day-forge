import { describe, it, expect } from "vitest"
import {
  computeEventBlockTimes,
  matchTravelRule,
} from "../src/utils/travelRules"
import type { TravelRule } from "../src/types"

function makeRule(overrides: Partial<TravelRule> & { id: number }): TravelRule {
  return {
    keyword: "dentist",
    travel_there_minutes: 30,
    travel_back_minutes: 30,
    category: "",
    order: 0,
    ...overrides,
  }
}

// Build an ISO8601 (UTC) string for a LOCAL wall-clock time so the tests
// are independent of the TZ the runner executes in — the util reads the
// event back via getHours()/getMinutes() in the same local TZ.
function isoLocal(
  y: number,
  m: number,
  d: number,
  h: number,
  min: number,
): string {
  return new Date(y, m - 1, d, h, min).toISOString()
}

const VIEWED = "2026-04-07"

describe("matchTravelRule", () => {
  it("matches case-insensitive substring", () => {
    const rules = [makeRule({ id: 1, keyword: "DeNtIsT" })]
    expect(matchTravelRule(rules, "Annual dentist visit")?.id).toBe(1)
  })

  it("first rule in server order wins on multiple matches", () => {
    const rules = [
      makeRule({ id: 1, keyword: "visit", order: 0 }),
      makeRule({ id: 2, keyword: "dentist", order: 1 }),
    ]
    expect(matchTravelRule(rules, "dentist visit")?.id).toBe(1)
  })

  it("returns null when nothing matches", () => {
    const rules = [makeRule({ id: 1, keyword: "gym" })]
    expect(matchTravelRule(rules, "dentist visit")).toBeNull()
  })

  it("skips rules whose keyword trims to empty", () => {
    const rules = [
      makeRule({ id: 1, keyword: "   " }),
      makeRule({ id: 2, keyword: "dentist" }),
    ]
    expect(matchTravelRule(rules, "dentist")?.id).toBe(2)
  })

  it("trims the keyword before matching", () => {
    const rules = [makeRule({ id: 1, keyword: "  dentist  " })]
    expect(matchTravelRule(rules, "dentist visit")?.id).toBe(1)
  })
})

describe("computeEventBlockTimes", () => {
  it("subtracts travel-there and adds travel-back", () => {
    const event = {
      start: isoLocal(2026, 4, 7, 14, 7),
      end: isoLocal(2026, 4, 7, 15, 0),
    }
    expect(computeEventBlockTimes(event, VIEWED, 30, 15)).toEqual({
      start_time: "13:37",
      end_time: "15:15",
    })
  })

  it("keeps exact off-grid minutes with zero travel", () => {
    const event = {
      start: isoLocal(2026, 4, 7, 14, 7),
      end: isoLocal(2026, 4, 7, 14, 33),
    }
    expect(computeEventBlockTimes(event, VIEWED, 0, 0)).toEqual({
      start_time: "14:07",
      end_time: "14:33",
    })
  })

  it("clamps a large travel-there to 00:00, never a prior calendar day", () => {
    const event = {
      start: isoLocal(2026, 4, 7, 8, 0),
      end: isoLocal(2026, 4, 7, 9, 0),
    }
    // 600 min before 08:00 lands at 22:00 of the previous day if the
    // shift is done on a Date object — the minutes-domain clamp must
    // produce 00:00 instead.
    expect(computeEventBlockTimes(event, VIEWED, 600, 0)).toEqual({
      start_time: "00:00",
      end_time: "09:00",
    })
  })

  it("clamps a large travel-back to 23:59", () => {
    const event = {
      start: isoLocal(2026, 4, 7, 22, 0),
      end: isoLocal(2026, 4, 7, 23, 30),
    }
    expect(computeEventBlockTimes(event, VIEWED, 0, 600)).toEqual({
      start_time: "22:00",
      end_time: "23:59",
    })
  })

  it("event span crossing midnight clamps the end to 23:59", () => {
    const event = {
      start: isoLocal(2026, 4, 7, 23, 0),
      end: isoLocal(2026, 4, 8, 0, 30),
    }
    // Naive same-day math would produce endMin=30 < startMin (inverted
    // range → backend 400); the endDelta fold yields 1470 → clamp 23:59.
    expect(computeEventBlockTimes(event, VIEWED, 0, 0)).toEqual({
      start_time: "23:00",
      end_time: "23:59",
    })
  })

  it("previous-day spillover clamps the start to 00:00 on the viewed day", () => {
    const event = {
      start: isoLocal(2026, 4, 6, 23, 0),
      end: isoLocal(2026, 4, 7, 0, 30),
    }
    // Anchoring to the event's start day would create 23:00–23:59 on the
    // wrong schedule; the startDelta = −1 fold pushes startMin to −60 → 00:00.
    expect(computeEventBlockTimes(event, VIEWED, 0, 0)).toEqual({
      start_time: "00:00",
      end_time: "00:30",
    })
  })

  it("returns null for an event entirely after the viewed local day", () => {
    // UTC-window artifact: the provider's UTC day can list an event that
    // is local 03:00 the NEXT calendar day.
    const event = {
      start: isoLocal(2026, 4, 8, 3, 0),
      end: isoLocal(2026, 4, 8, 4, 0),
    }
    expect(computeEventBlockTimes(event, VIEWED, 0, 0)).toBeNull()
  })

  it("returns null for an event entirely before the viewed local day", () => {
    const event = {
      start: isoLocal(2026, 4, 6, 10, 0),
      end: isoLocal(2026, 4, 6, 11, 0),
    }
    expect(computeEventBlockTimes(event, VIEWED, 0, 0)).toBeNull()
  })

  it("returns null when the event range is inverted after clamping", () => {
    // Corrupt/backwards event: end before start on the viewed day.
    const event = {
      start: isoLocal(2026, 4, 7, 15, 0),
      end: isoLocal(2026, 4, 7, 14, 0),
    }
    expect(computeEventBlockTimes(event, VIEWED, 0, 0)).toBeNull()
  })

  it("returns an equal pair for a zero-length event with no travel", () => {
    // DTEND-less CalDAV events normalize to dtend = dtstart; the dialog
    // shows its zero-length hint on start === end and disables Confirm.
    const event = {
      start: isoLocal(2026, 4, 7, 14, 7),
      end: isoLocal(2026, 4, 7, 14, 7),
    }
    expect(computeEventBlockTimes(event, VIEWED, 0, 0)).toEqual({
      start_time: "14:07",
      end_time: "14:07",
    })
  })

  it("travel minutes stretch a zero-length event into a real range", () => {
    const event = {
      start: isoLocal(2026, 4, 7, 14, 7),
      end: isoLocal(2026, 4, 7, 14, 7),
    }
    expect(computeEventBlockTimes(event, VIEWED, 10, 10)).toEqual({
      start_time: "13:57",
      end_time: "14:17",
    })
  })
})
