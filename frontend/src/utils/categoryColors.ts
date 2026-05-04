// Single source of truth for category → swatch colour. Imported by
// TimeBlock.vue (the canonical block renderer) and by the analytics
// components (CategoryBreakdown). Keeping this in one module avoids the
// drift bug where the schedule view and the analytics view show
// different colours for the same category.

import type { TimeBlock } from "../types"

export const categoryColors: Record<TimeBlock["category"], string> = {
  work: "#3B82F6",
  personal: "#8B5CF6",
  health: "#10B981",
  other: "#6B7280",
}
