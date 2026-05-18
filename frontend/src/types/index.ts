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

export interface UndoAction {
  description: string
  type: "drag" | "edit" | "toggle" | "add" | "delete" | "ai" | "draft"
  previousBlocks: TimeBlock[]
  scheduleDate: string
}

export interface TemplateBlock {
  title: string
  start_time: string // "HH:MM"
  end_time: string // "HH:MM"
  category: "work" | "personal" | "health" | "other"
}

export interface Template {
  id: number
  name: string
  type: "weekday" | "weekend"
  blocks: TemplateBlock[]
}

export interface Rule {
  id: number
  text: string
  is_active: boolean
  priority: number
}

// Keyed off the existing TimeBlock category union so adding/renaming a
// category surfaces a compile error wherever this type is consumed.
export type CategoryMinutes = Record<TimeBlock["category"], number>

export interface DailyReview {
  id: number
  schedule_id: number
  date: string // "YYYY-MM-DD"
  status: Schedule["status"]
  planned_count: number
  completed_count: number
  skipped_count: number
  // null when planned_count === 0 (rest day) — distinguishes from 0% completed.
  completion_rate: number | null
  planned_minutes_by_category: CategoryMinutes
  completed_minutes_by_category: CategoryMinutes
  notes: string
  created_at: string
  updated_at: string
}

export interface StreakInfo {
  current: number
  threshold: number
  window_days: number
}

export type ThemeId = "classic" | "strategic" | "light_premium"

export interface UiPreferences {
  theme: ThemeId
}

// Augment Inertia's shared PageProps so every `usePage()` call site can
// reach `page.props.ui_preferences` without an inline generic.
//
// The augmentation target is @inertiajs/core (where PageProps is defined),
// not @inertiajs/vue3 — augmenting the latter would miss the actual type
// and leave the property typed as `unknown`.
declare module "@inertiajs/core" {
  interface PageProps {
    ui_preferences?: UiPreferences
  }
}
