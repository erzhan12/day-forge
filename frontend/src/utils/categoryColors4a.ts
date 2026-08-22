import type { TimeBlock } from "../types"

// Kept separate from categoryColors: callers there concatenate hex alpha
// suffixes, which would not work with these deliberate oklch values.
export const categoryColors4a: Record<TimeBlock["category"], string> = {
  work: "oklch(0.72 0.12 250)",
  personal: "oklch(0.75 0.12 150)",
  health: "oklch(0.75 0.12 150)",
  other: "oklch(0.78 0.12 75)",
}
