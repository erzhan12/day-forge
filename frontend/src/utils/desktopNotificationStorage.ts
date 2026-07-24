export const DESKTOP_NOTIFICATIONS_KEY = "day-forge:desktop-notifications:enabled"

// Strict-only-on-true semantics: only the literal boolean `true` enables
// desktop notifications. Missing key, malformed JSON, or any non-true value
// defaults to disabled (`false`). Mirrors soundNotificationStorage.ts — the
// safe failure mode is SILENCE, so a corrupted or hand-edited value must
// never surprise the user with unexpected notifications. The composable also
// only ever persists `true` AFTER Notification permission is `granted`.
// See docs/features/0028_PLAN.md Phase 1.
export function readDesktopNotificationsEnabled(): boolean {
  try {
    const raw = localStorage.getItem(DESKTOP_NOTIFICATIONS_KEY)
    if (raw === null) return false
    return JSON.parse(raw) === true
  } catch {
    return false
  }
}

export function writeDesktopNotificationsEnabled(v: boolean): void {
  try {
    localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, JSON.stringify(v))
  } catch {
    // private-mode browsers / disk-quota — fall back to in-memory only
  }
}
