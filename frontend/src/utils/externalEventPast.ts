import type { NormalizedEvent } from "../types/calendar"

/** Local minutes-since-midnight for an ISO8601 instant. */
function isoToLocalMinutes(iso: string): number {
  const d = new Date(iso)
  return d.getHours() * 60 + d.getMinutes()
}

/**
 * True when an external calendar row should render as past/faded.
 * - Past viewed dates: every event is past.
 * - Future viewed dates: none are past.
 * - Today: timed events whose end is at or before `nowMinutes`; all-day
 *   events stay full strength for the whole day.
 */
export function isExternalEventPast(
  ev: NormalizedEvent,
  viewedDate: string,
  today: string,
  nowMinutes: number | null,
): boolean {
  if (viewedDate < today) return true
  if (viewedDate > today) return false
  if (ev.all_day) return false
  if (nowMinutes === null) return false
  return isoToLocalMinutes(ev.end) <= nowMinutes
}
