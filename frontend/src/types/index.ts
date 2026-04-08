export interface TimeBlock {
  id: number
  title: string
  start_time: string // "HH:MM"
  end_time: string // "HH:MM"
  category: "work" | "personal" | "health" | "other"
  is_completed: boolean
  sort_order: number
}

export interface Schedule {
  id: number
  date: string // "YYYY-MM-DD"
  status: "draft" | "active" | "reviewed"
}

export interface RenderItem {
  type: "block" | "gap"
  block?: TimeBlock
  start_time: string
  end_time: string
  duration_minutes: number
}
