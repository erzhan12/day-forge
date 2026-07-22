export interface HabiticaTask {
  id: string
  title: string
  type: "todo" | "daily"
  due_date: string | null
  completed: boolean
}

export interface HabiticaAccountStatus {
  connected: boolean
  last_verified_at: string | null
  api_user_id: string | null
}
