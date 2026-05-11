export const CHAT_SIDEBAR_OPEN_KEY = "day-forge:chat-sidebar:open"

// Strict-only-on-false semantics: only the literal boolean `false`
// collapses the sidebar. Missing key, malformed JSON, or any non-false
// value defaults to open (`true`). This prevents an accidental lockout
// if localStorage is corrupted or hand-edited — the sidebar is the only
// AI entry point on wide screens, so "open" is the safe failure mode.
export function readChatSidebarOpen(): boolean {
  try {
    const raw = localStorage.getItem(CHAT_SIDEBAR_OPEN_KEY)
    if (raw === null) return true
    return JSON.parse(raw) === false ? false : true
  } catch {
    return true
  }
}

export function writeChatSidebarOpen(v: boolean): void {
  try {
    localStorage.setItem(CHAT_SIDEBAR_OPEN_KEY, JSON.stringify(v))
  } catch {
    // private-mode browsers / disk-quota — fall back to in-memory only
  }
}
