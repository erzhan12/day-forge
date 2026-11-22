import { formatDurationMinutes } from "./scheduleTime"

/** Dark 4a gap row label: `Free · 2h 50m` (feature 0106). */
export function formatGapLabel(minutes: number): string {
  return `Free · ${formatDurationMinutes(minutes)}`
}

/** Dark 4a gap row range: `12:10–15:00`, an en dash with no spaces. */
export function formatGapRange(startTime: string, endTime: string): string {
  return `${startTime}–${endTime}`
}
