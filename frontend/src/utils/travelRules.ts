// Travel-rule matching + event→block time mapping (feature 0026).
//
// Pure functions — the dialog computes final local HH:MM here and POSTs
// them; the backend from-event endpoint stays TZ-agnostic.
import type { TravelRule } from "../types"
import type { NormalizedEvent } from "../types/calendar"

import { civilDayDelta, zonedDateTime } from "./date"
const LAST_MINUTE = 23 * 60 + 59 // 23:59 clamp ceiling

/**
 * Keyword rules (ascending `order`, server-sorted) match before calendar-only
 * rules. A keyword rule may constrain itself to one calendar; empty calendar
 * name means any calendar. `rules` must already be in server order — do not
 * re-sort here.
 */
export function matchTravelRule(
  rules: TravelRule[],
  title: string,
  calendarName = "",
): TravelRule | null {
  const haystack = title.toLowerCase()

  // Keyword rules always take precedence over calendar-only rules, regardless
  // of their relative order values.
  for (const rule of rules) {
    const needle = rule.keyword.trim().toLowerCase()
    if (needle === "" || !haystack.includes(needle)) continue
    const ruleCalendarName = (rule.calendar_name ?? "").trim()
    if (
      ruleCalendarName === "" ||
      calendarNamesEqual(ruleCalendarName, calendarName)
    ) {
      return rule
    }
  }

  // Calendar-only rules must name a calendar. Do not let a legacy degenerate
  // empty/empty row match every event that lacks a calendar name.
  for (const rule of rules) {
    if (rule.keyword.trim() !== "") continue
    const ruleCalendarName = (rule.calendar_name ?? "").trim()
    if (
      ruleCalendarName !== "" &&
      calendarNamesEqual(ruleCalendarName, calendarName)
    ) {
      return rule
    }
  }
  return null
}

function calendarNamesEqual(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase()
}

/** Map event wall-clock times and travel padding into the viewed day.
 * Naive HH:MM blocks cannot distinguish the two occurrences of a DST hour.
 * All-day events use calendar dates; their UTC serialization is not authority.
 */
export function computeEventBlockTimes(
  event: Pick<NormalizedEvent, "start" | "end"> & Partial<Pick<NormalizedEvent, "all_day" | "start_date" | "end_date">>,
  viewedDate: string,
  travelThere: number,
  travelBack: number,
  timeZone = "UTC",
): { start_time: string; end_time: string } | null {
  const start = event.all_day && event.start_date
    ? { date: event.start_date, minutes: 0 }
    : zonedDateTime(new Date(event.start), timeZone)
  const end = event.all_day && event.end_date
    ? { date: event.end_date, minutes: 0 }
    : zonedDateTime(new Date(event.end), timeZone)
  let startMin = start.minutes + civilDayDelta(viewedDate, start.date) * 1440 - travelThere
  let endMin = end.minutes + civilDayDelta(viewedDate, end.date) * 1440 + travelBack

  // Out-of-day guard before the clamp: blindly clamping an event lying
  // entirely outside the viewed local day would produce a nonsense range.
  if (endMin <= 0 || startMin >= 1440) return null

  startMin = Math.max(0, startMin)
  endMin = Math.min(LAST_MINUTE, endMin)

  // Inverted after clamp (corrupt/backwards event) — Confirm disabled.
  // Equal times stay (zero-length dialog hint).
  if (startMin > endMin) return null

  return { start_time: formatMinutes(startMin), end_time: formatMinutes(endMin) }
}

function formatMinutes(min: number): string {
  const h = String(Math.floor(min / 60)).padStart(2, "0")
  const m = String(min % 60).padStart(2, "0")
  return `${h}:${m}`
}
