import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"
import { formatBlockDuration, formatDailyExport } from "../src/utils/dailyExport"

// Shared backend/frontend parity fixtures (feature 0088). Read via Node `fs`
// with a path relative to the repo root, not a Vite import, so no `fs.allow`
// change is needed. `schedules.daily_export.format_daily_export` (Python)
// must render byte-identical Markdown from these same cases — see
// `backend/tests/test_daily_export.py`.
function loadFixture(name: string): any[] {
  const path = resolve(__dirname, "../../backend/tests/fixtures/daily_export", name)
  return JSON.parse(readFileSync(path, "utf-8"))
}

const MARKDOWN_CASES = loadFixture("markdown.json")
const NOTES_CASES = loadFixture("notes.json")

describe("formatBlockDuration", () => {
  it.each([
    ["09:00", "09:15", "15m"],
    ["09:00", "10:00", "1h"],
    ["09:00", "10:30", "1h 30m"],
    ["09:00", "11:30", "2h 30m"],
  ])("formats %s–%s as %s", (start, end, expected) => {
    expect(formatBlockDuration(start, end)).toBe(expected)
  })
})

describe("formatDailyExport", () => {
  it("renders the exact markdown format, sorted without mutating stored block values", () => {
    const blocks = [
      {
        title: "Later task",
        start_time: "10:00",
        end_time: "11:30",
        category: "other",
        is_completed: false,
        sort_order: 1,
      },
      {
        title: "Morning\nrun",
        start_time: "08:00",
        end_time: "08:45",
        category: "health",
        is_completed: true,
        sort_order: 1,
      },
      {
        title: "Reading",
        start_time: "10:00",
        end_time: "10:30",
        category: "reading",
        is_completed: false,
      },
      {
        title: "Standup",
        start_time: "09:00",
        end_time: "09:15",
        category: "work",
        is_completed: true,
        sort_order: 0,
      },
    ]
    const snapshot = JSON.parse(JSON.stringify(blocks))

    expect(formatDailyExport({ date: "2026-08-29", blocks })).toBe(
      "## day-forge · 2026-08-29\n\n" +
        "blocks: 2/4 done\n\n" +
        "- [x] 08:00 Morning\nrun (health) 45m\n" +
        "- [x] 09:00 Standup (work) 15m\n" +
        "- [ ] 10:00 Reading (reading) 30m\n" +
        "- [ ] 10:00 Later task 1h 30m",
    )
    expect(blocks).toEqual(snapshot)
  })

  it("keeps an empty export to its header and summary without a trailing newline", () => {
    expect(formatDailyExport({ date: "2026-08-29", blocks: [] })).toBe(
      "## day-forge · 2026-08-29\n\nblocks: 0/0 done",
    )
  })

  it("normalizes a note and omits blank notes", () => {
    const blocks = [{ title: "Gym", start_time: "09:00", end_time: "10:00", category: "health", is_completed: false }]
    expect(formatDailyExport({ date: "2026-08-29", blocks, note: "  done\t with\ncare  " })).toBe(
      "## day-forge · 2026-08-29\n\nblocks: 0/1 done\n\n- [ ] 09:00 Gym (health) 1h\n\nnote: done with care",
    )
    expect(formatDailyExport({ date: "2026-08-29", blocks, note: " \n\t " })).not.toContain("note:")
  })

  it("does not mutate the input blocks array", () => {
    const blocks = [
      {
        title: "Later task", start_time: "10:00", end_time: "11:30",
        category: "other", is_completed: false, sort_order: 1,
      },
      {
        title: "Morning run", start_time: "08:00", end_time: "08:45",
        category: "health", is_completed: true,
      },
    ]
    const snapshot = JSON.parse(JSON.stringify(blocks))
    formatDailyExport({ date: "2026-08-29", blocks, note: "  hi  " })
    expect(blocks).toEqual(snapshot)
  })
})

describe("formatDailyExport (shared backend/frontend fixtures)", () => {
  it.each(MARKDOWN_CASES.map((c) => [c.name, c]))("%s", (_name, testCase) => {
    const result = formatDailyExport({ date: testCase.date, blocks: testCase.blocks })
    expect(result).toBe(testCase.expected)
  })

  it.each(NOTES_CASES.map((c) => [c.name, c]))("%s", (_name, testCase) => {
    const args: { date: string; blocks: any[]; note?: string } = {
      date: testCase.date,
      blocks: testCase.blocks,
    }
    if (testCase.note_present) args.note = testCase.note
    const result = formatDailyExport(args)
    expect(result).toBe(testCase.expected)
  })
})
