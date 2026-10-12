export interface ZonedDateTime {
  date: string
  hours: number
  minute: number
  minutes: number
  hhmm: string
}

const formatters = new Map<string, Intl.DateTimeFormat>()

function formatter(timeZone: string): Intl.DateTimeFormat {
  let value = formatters.get(timeZone)
  if (!value) {
    value = new Intl.DateTimeFormat("en-US-u-ca-gregory-nu-latn", {
      timeZone,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    })
    formatters.set(timeZone, value)
  }
  return value
}

/** Read civil date and clock from the same instant in the saved IANA zone. */
export function zonedDateTime(instant: Date, timeZone: string): ZonedDateTime {
  let parts: Intl.DateTimeFormatPart[]
  try {
    parts = formatter(timeZone).formatToParts(instant)
  } catch {
    // Corrupt legacy settings must never make the schedule unusable.
    parts = formatter("UTC").formatToParts(instant)
  }
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  const hours = Number(values.hour)
  const minute = Number(values.minute)
  return {
    date: `${values.year}-${values.month}-${values.day}`,
    hours,
    minute,
    minutes: hours * 60 + minute,
    hhmm: `${values.hour}:${values.minute}`,
  }
}

/** Civil date in the saved timezone. Browser timezone is never authoritative. */
export function todayString(timeZone = "UTC", instant = new Date()): string {
  return zonedDateTime(instant, timeZone).date
}

function utcCivilDate(dateStr: string): Date {
  const [year, month, day] = dateStr.split("-").map(Number)
  const result = new Date(0)
  result.setUTCFullYear(year, month - 1, day)
  result.setUTCHours(12, 0, 0, 0)
  return result
}

export function civilDayDelta(from: string, to: string): number {
  return Math.round((utcCivilDate(to).getTime() - utcCivilDate(from).getTime()) / 86_400_000)
}

export function addCivilDays(date: string, offset: number): string {
  const result = utcCivilDate(date)
  result.setUTCDate(result.getUTCDate() + offset)
  return result.toISOString().slice(0, 10)
}

export function formatCivilDate(date: string, locale = "en-US"): string {
  return utcCivilDate(date).toLocaleDateString(locale, {
    timeZone: "UTC", weekday: "long", year: "numeric",
    month: "long", day: "numeric",
  })
}
