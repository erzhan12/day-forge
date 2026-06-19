// Normalised task shape returned by GET /api/todoist/tasks/<date>/.
// Wire-format is JSON; `title` is the task name (never `content`),
// `priority` is the raw Todoist int 1-4 (4 = highest), `ui_priority` is the
// precomputed UI flag "P1".."P4", `due_date` is an ISO date string
// ("YYYY-MM-DD") or null when the task has no due date.
export interface TodoistTask {
  id: string
  title: string
  priority: number
  ui_priority: string
  due_date: string | null
}

// Status payload returned by GET/POST/DELETE /api/todoist/account/.
export interface TodoistAccountStatus {
  connected: boolean
  last_verified_at: string | null
}
