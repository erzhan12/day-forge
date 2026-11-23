import type { NormalizedEvent } from "../types/calendar"
import { formatDurationMinutes } from "./scheduleTime"

const EMAIL = /^[^\s@]+@[^\s@]+$/

export function eventDurationMinutes(ev: NormalizedEvent): number {
  return Math.round((new Date(ev.end).getTime() - new Date(ev.start).getTime()) / 60_000)
}

/**
 * Calendar card subtitle (feature 0106): the calendar's own name, else the
 * account label, with an email shortened to its local part, joined with the
 * event duration (`Work · 1h`). All-day and non-positive durations show no
 * duration; nothing is invented when both names are empty.
 */
export function eventSourceLabel(ev: NormalizedEvent): string {
  let name = ev.calendar_name.trim() || ev.account_label.trim()
  if (EMAIL.test(name)) name = name.slice(0, name.indexOf("@"))
  const minutes = eventDurationMinutes(ev)
  const duration = !ev.all_day && minutes > 0 ? formatDurationMinutes(minutes) : ""
  return [name, duration].filter(Boolean).join(" · ")
}
