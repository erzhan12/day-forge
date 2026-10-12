import type { NormalizedEvent } from "../types/calendar"

import { civilDayDelta, zonedDateTime } from "./date"

/**
 * True when an external calendar row should render as past/faded.
 * - Past viewed dates: every event is past.
 * - Future viewed dates: none are past.
 * - Today: timed events whose end is at or before `nowMinutes`; all-day
 *   events stay full strength for the whole day. The end is folded across
 *   calendar days first (`localDayDelta`), so an overnight event ending on a
 *   later local day (e.g. 23:00 -> 00:30 +1d) is not mistaken for past.
 */
export function isExternalEventPast(
  ev: NormalizedEvent,
  viewedDate: string,
  today: string,
  nowMinutes: number | null,
  timeZone = "UTC",
): boolean {
  if (viewedDate < today) return true
  if (viewedDate > today) return false
  if (ev.all_day) return false
  if (nowMinutes === null) return false
  const end = zonedDateTime(new Date(ev.end), timeZone)
  const foldedEndMinutes = civilDayDelta(today, end.date) * 1440 + end.minutes
  return foldedEndMinutes <= nowMinutes
}
