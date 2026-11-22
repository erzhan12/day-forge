import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

// Feature 0106 hard constraint: calendar events never reach the schedule
// timeline on their own. An event enters the day only through the explicit
// "Add to schedule" import, which creates a block. These modules build and
// render the timeline, so none of them may depend on the calendar types or
// the external-source composables.

const SRC = resolve(__dirname, "..", "src")

const TIMELINE_MODULES = [
  "composables/useTimelinePresentation.ts",
  "utils/scheduleTime.ts",
  "utils/timelineStack.ts",
  "components/Timeline4a.vue",
  "components/GapSlot4a.vue",
  "components/TimeBlock4a.vue",
]

const FORBIDDEN_IMPORTS = [
  /types\/calendar/,
  /useExternalSources/,
  /useCalendar\b/,
  /useGoogleCalendar/,
]

function readIfPresent(rel: string): string | null {
  try {
    return readFileSync(resolve(SRC, rel), "utf-8")
  } catch {
    return null
  }
}

describe("calendar events stay off the timeline (0106)", () => {
  for (const rel of TIMELINE_MODULES) {
    it(`${rel} imports no calendar source and never mentions NormalizedEvent`, () => {
      const source = readIfPresent(rel)
      if (source === null) {
        // timelineStack.ts arrives in Phase 2; scanned once it exists.
        expect(rel).toBe("utils/timelineStack.ts")
        return
      }
      const imports = source
        .split("\n")
        .filter((line) => /^\s*import\b/.test(line) || /from\s+["']/.test(line))
      for (const pattern of FORBIDDEN_IMPORTS) {
        for (const line of imports) {
          expect(line, `${rel}: ${line}`).not.toMatch(pattern)
        }
      }
      expect(source).not.toMatch(/NormalizedEvent/)
    })
  }
})
