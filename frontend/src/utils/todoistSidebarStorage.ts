export const TODOIST_SIDEBAR_OPEN_KEY = "day-forge:todoist-sidebar:open"

// Strict-only-on-false semantics — mirrors chatSidebarStorage.ts.
export function readTodoistSidebarOpen(): boolean {
  try {
    const raw = localStorage.getItem(TODOIST_SIDEBAR_OPEN_KEY)
    if (raw === null) return true
    return JSON.parse(raw) === false ? false : true
  } catch {
    return true
  }
}

export function writeTodoistSidebarOpen(v: boolean): void {
  try {
    localStorage.setItem(TODOIST_SIDEBAR_OPEN_KEY, JSON.stringify(v))
  } catch {
    // private-mode browsers / disk-quota — fall back to in-memory only
  }
}
