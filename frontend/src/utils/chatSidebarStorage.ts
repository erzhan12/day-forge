export const CHAT_SIDEBAR_OPEN_KEY = "day-forge:chat-sidebar:open"

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
