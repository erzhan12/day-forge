import type { TimeBlock } from "../types"
import {
  buildBaseDisplayItems,
  type ScheduleDisplayItem,
  type ScheduleWindowBounds,
} from "./scheduleTime"

// Rows of the Dark 4a phone list (feature 0113, SPEC 11.3): the day's blocks
// and every free gap, in time order, with no time scale. The base builder runs
// with the whole window as its render range and no clock, so edge gaps are
// whole and the trailing gap is never split at "now". Inert spacers (legacy
// blocks outside the window) are dropped; blocks that touch leave no gap row.
export type MobileRow =
  | { kind: "block"; key: string; block: TimeBlock }
  | { kind: "gap"; key: string; start_time: string; end_time: string; duration_minutes: number }

export function buildMobileRows(blocks: TimeBlock[], window: ScheduleWindowBounds): MobileRow[] {
  const items: ScheduleDisplayItem[] = buildBaseDisplayItems(
    blocks, window.startMinutes, window.endMinutes, null, window,
  )
  const rows: MobileRow[] = []
  for (const item of items) {
    if (item.type === "block" && item.block) {
      rows.push({ kind: "block", key: `b${item.block.id}`, block: item.block })
    } else if (item.type === "gap" && item.duration_minutes > 0) {
      rows.push({
        kind: "gap",
        key: `g${item.start_time}-${item.end_time}`,
        start_time: item.start_time,
        end_time: item.end_time,
        duration_minutes: item.duration_minutes,
      })
    }
  }
  return rows
}
