// Shared HTTP plumbing for composables that hit Day Forge's Django JSON API.
//
// The backend overrides Django's default CSRF cookie (`csrftoken` /
// `X-CSRFToken`) to the Inertia/Axios convention: `XSRF-TOKEN` cookie +
// `X-XSRF-TOKEN` header. The matching Django settings live in
// backend/day_forge/settings.py as CSRF_COOKIE_NAME and CSRF_HEADER_NAME —
// if either side changes, change both.
//
// Cancellation: pass `{ signal }` as the fourth arg to abort an in-flight
// request. `AbortError` propagates as a thrown rejection (not the usual
// `{ok: false, errors: {...}}` envelope) so callers can swallow it cleanly
// in the stale-response guard pattern used by `useCalendar` / `useCalendarAccount`.
// GET-call shape footgun: pass `undefined` as the third positional arg, NOT
// the options object — `requestJson(url, "GET", { signal })` would serialise
// the options as the JSON body.

export function getCsrfToken(): string {
  const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ""
}

export interface ApiResult {
  ok: boolean
  status?: number
  data?: Record<string, unknown>
  errors?: Record<string, string | string[]>
}

/**
 * Low-level request wrapper used by `useSchedule` and `useAI`.
 *
 * Handles CSRF, JSON (de)serialisation, and the common `{ok, data, errors}`
 * envelope. Always reads the body as text first and parses conditionally —
 * a 200 with an empty body returns `{ok: true}` with no `data`, matching
 * the batch-restore / reorder endpoints that reply with empty payloads.
 * Callers add their own side-effects (e.g. `router.reload`, health-state
 * flips) on top.
 */
export interface RequestOptions {
  signal?: AbortSignal
}

export async function requestJson(
  url: string,
  method: string,
  body?: Record<string, unknown>,
  options?: RequestOptions,
): Promise<ApiResult> {
  let resp: Response
  try {
    resp = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": getCsrfToken(),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: options?.signal,
    })
  } catch (err) {
    // Rethrow `AbortError` so callers in the stale-response guard pattern
    // (`useCalendar`, `useCalendarAccount`) can swallow it without flipping
    // their `loading` / `error` state — the superseding op owns that.
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err
    }
    return {
      ok: false,
      errors: { detail: "Network error. Please check your connection." },
    }
  }

  const text = await resp.text()
  let data: Record<string, unknown> | undefined
  let parseFailed = false
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      parseFailed = true
    }
  }

  if (resp.ok) {
    if (parseFailed) {
      return {
        ok: false,
        status: resp.status,
        errors: { detail: "Invalid server response." },
      }
    }
    return { ok: true, status: resp.status, data }
  }

  // Non-OK: surface the server's structured ``errors`` if present; otherwise
  // fall back to a generic "Server error (N)" so the user sees the status.
  const errors = (data?.errors as ApiResult["errors"]) ?? {
    detail: `Server error (${resp.status})`,
  }
  return { ok: false, status: resp.status, errors }
}
