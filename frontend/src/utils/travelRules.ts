// Travel-rule matching + event→block time mapping (feature 0026).
//
// Pure functions — the dialog computes final local HH:MM here and POSTs
// them; the backend from-event endpoint stays TZ-agnostic.
import type { TravelRule } from "../types"
import type { NormalizedEvent } from "../types/calendar"

const DAY_MS = 86_400_000
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

/**
 * Map an external event ± travel minutes onto the VIEWED day's local
 * `HH:MM` range, clamped to `[00:00, 23:59]`.
 *
 * Everything anchors to the viewed date's local midnight, not the event's
 * start day: both providers return every event *overlapping* the fetch
 * window (a UTC day, per `settings.TIME_ZONE`), so the panel can show an
 * event that started the previous local day (e.g. 23:00(prev)→00:30) —
 * anchoring to the event's start day would create 23:00–23:59 on the
 * wrong schedule.
 *
 * Works in the minutes domain: read each value's local clock time, fold
 * in the whole-day delta to the viewed day, then apply travel. Shifting
 * the Date object and re-reading getHours() would let a large travel
 * value land on another calendar day, defeating the clamp.
 *
 * Returns `null` when the event ± travel does not intersect the viewed
 * local day at all (UTC-window artifact — e.g. a local 03:00 next-day
 * event listed on the viewed UTC day), or when the range is inverted
 * after clamping (`startMin > endMin`); callers disable Confirm on `null`.
 * A zero-length result (start_time === end_time, e.g. a DTEND-less CalDAV
 * event with 0/0 travel) is returned as-is so the dialog can show its
 * distinct zero-length hint.
 */
export function computeEventBlockTimes(
  event: Pick<NormalizedEvent, "start" | "end">,
  viewedDate: string,
  travelThere: number,
  travelBack: number,
): { start_time: string; end_time: string } | null {
  const startLocal = new Date(event.start)
  const endLocal = new Date(event.end)
  const [y, m, d] = viewedDate.split("-").map(Number)
  const viewedDay = new Date(y, m - 1, d)

  const startDay = new Date(
    startLocal.getFullYear(),
    startLocal.getMonth(),
    startLocal.getDate(),
  )
  const endDay = new Date(
    endLocal.getFullYear(),
    endLocal.getMonth(),
    endLocal.getDate(),
  )
  // Whole calendar days; Math.round absorbs the DST ±1h so the ratio
  // still lands on an integer.
  const startDelta = Math.round(
    (startDay.getTime() - viewedDay.getTime()) / DAY_MS,
  )
  const endDelta = Math.round((endDay.getTime() - viewedDay.getTime()) / DAY_MS)

  let startMin =
    startLocal.getHours() * 60 +
    startLocal.getMinutes() +
    startDelta * 1440 -
    travelThere
  let endMin =
    endLocal.getHours() * 60 +
    endLocal.getMinutes() +
    endDelta * 1440 +
    travelBack

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
