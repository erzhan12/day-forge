// Normalised event shape returned by GET /api/calendar/events/<date>/ and
// GET /api/calendar/google/events/<date>/. Wire-format is JSON; `start` /
// `end` are ISO8601 strings (UTC). `account_label` (feature 0022) is the
// connecting-account label — empty string for Apple (single account, no
// label), the account email for Google.
export interface NormalizedEvent {
  title: string
  start: string
  end: string
  calendar_name: string
  all_day: boolean
  external_uid: string
  account_label: string
}

// Status payload returned by GET/POST/DELETE /api/calendar/account/.
export interface CalDAVAccountStatus {
  connected: boolean
  apple_id: string | null
  base_url: string | null
  last_verified_at: string | null
  default_base_url: string
}

// ----- Google Calendar (feature 0022) -----------------------------------

// One connected Google account, returned by GET /api/calendar/google/accounts/.
export interface GoogleAccount {
  id: number
  email: string
  last_verified_at: string | null
}

// A per-account failure in the composite events response. `reconnect_required`
// → the user must re-grant (auth revoked); `unavailable` → transient
// provider/timeout failure.
export interface GoogleAccountError {
  account_id: number
  email: string
  error: "reconnect_required" | "unavailable"
}

// Composite response shape from GET /api/calendar/google/events/<date>/.
// `account_errors` is always present (empty list when all accounts loaded).
export interface GoogleEventsResponse {
  events: NormalizedEvent[]
  account_errors: GoogleAccountError[]
}

// One whole-request provider failure banner rendered by ExternalEventsPanel.
// Distinct from per-account `GoogleAccountError`s — these come from an HTTP
// error on the provider's events call, not a 200 + account_errors entry.
export interface ProviderErrorBanner {
  provider: "apple" | "google"
  message: string
}
