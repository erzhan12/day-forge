import { weekdayName } from "./date"

export interface EmptyDayCopy {
  title: string
  primaryLabel: string
}

/** Copy for the Dark 4a empty day without a template (feature 0106). */
export function emptyDayCopy(date: string, slotType: "weekday" | "weekend"): EmptyDayCopy {
  return {
    title: `No template for ${weekdayName(date)}`,
    primaryLabel: slotType === "weekend" ? "Create weekend template" : "Create weekday template",
  }
}
