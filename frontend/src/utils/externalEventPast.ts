import type { NormalizedEvent } from "../types/calendar"

/** Local minutes-since-midnight for an ISO8601 instant. */
function isoToLocalMinutes(iso: string): number {
  const d = new Date(iso)
  return d.getHours() * 60 + d.getMinutes()
}

/** DST-safe local civil-day difference from `today` to the local date of `iso`. */
function localDayDelta(today: string, iso: string): number {
  const [y, m, d] = today.split("-").map(Number)
  const todayMidnight = new Date(y, m - 1, d)
  const endDate = new Date(iso)
  const endMidnight = new Date(
    endDate.getFullYear(),
    endDate.getMonth(),
    endDate.getDate(),
  )
  return Math.round(
    (endMidnight.getTime() - todayMidnight.getTime()) / 86400000,
  )
}

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
): boolean {
  if (viewedDate < today) return true
  if (viewedDate > today) return false
  if (ev.all_day) return false
  if (nowMinutes === null) return false
  const dayDelta = localDayDelta(today, ev.end)
  const foldedEndMinutes = dayDelta * 1440 + isoToLocalMinutes(ev.end)
  return foldedEndMinutes <= nowMinutes
}
