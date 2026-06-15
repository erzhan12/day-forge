export const SOUND_NOTIFICATIONS_KEY = "day-forge:sound-notifications:enabled"

// Strict-only-on-true semantics: only the literal boolean `true` enables
// sound notifications. Missing key, malformed JSON, or any non-true value
// defaults to disabled (`false`). This is the inverse of the chat-sidebar
// key (strict-only-on-false) because the safe failure mode here is
// SILENCE — a corrupted or hand-edited value must never surprise the user
// with unexpected audio. See docs/features/0019_PLAN.md Phase 1.
export function readSoundNotificationsEnabled(): boolean {
  try {
    const raw = localStorage.getItem(SOUND_NOTIFICATIONS_KEY)
    if (raw === null) return false
    return JSON.parse(raw) === true ? true : false
  } catch {
    return false
  }
}

export function writeSoundNotificationsEnabled(v: boolean): void {
  try {
    localStorage.setItem(SOUND_NOTIFICATIONS_KEY, JSON.stringify(v))
  } catch {
    // private-mode browsers / disk-quota — fall back to in-memory only
  }
}
