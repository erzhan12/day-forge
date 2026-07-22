export const EXTERNAL_TASKS_SIDEBAR_OPEN_KEY =
  "day-forge:todoist-sidebar:open"

// Strict-only-on-false semantics — mirrors chatSidebarStorage.ts.
export function readExternalTasksSidebarOpen(): boolean {
  try {
    const raw = localStorage.getItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY)
    if (raw === null) return true
    return JSON.parse(raw) === false ? false : true
  } catch {
    return true
  }
}

export function writeExternalTasksSidebarOpen(v: boolean): void {
  try {
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, JSON.stringify(v))
  } catch {
    // private-mode browsers / disk-quota — fall back to in-memory only
  }
}
