// Normalised event shape returned by GET /api/calendar/events/<date>/.
// Wire-format is JSON; `start` / `end` are ISO8601 strings (UTC).
export interface NormalizedEvent {
  title: string
  start: string
  end: string
  calendar_name: string
  all_day: boolean
  external_uid: string
}

// Status payload returned by GET/POST/DELETE /api/calendar/account/.
export interface CalDAVAccountStatus {
  connected: boolean
  apple_id: string | null
  base_url: string | null
  last_verified_at: string | null
  default_base_url: string
}
