// SYNC ALERT: keep these defaults and limits aligned with
// `backend/templates_mgr/preferences.py`.
export const DEFAULT_CHAT_SUGGESTIONS = [
  "Plan my remaining day",
  "Add a focused work block",
  "Make room for a break",
] as const

export const MAX_CHAT_SUGGESTIONS = 8
export const MAX_CHAT_SUGGESTION_CHARS = 120

export function resolveChatSuggestions(raw: unknown): string[] {
  if (!Array.isArray(raw) || !raw.every((item) => typeof item === "string")) {
    return [...DEFAULT_CHAT_SUGGESTIONS]
  }
  return [...raw]
}
