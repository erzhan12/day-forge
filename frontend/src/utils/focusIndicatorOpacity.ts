// SYNC ALERT: mirror backend/templates_mgr/models.py exactly.
export const FOCUS_INDICATOR_OPACITY_MIN = 0.20
export const FOCUS_INDICATOR_OPACITY_MAX = 1.00
export const FOCUS_INDICATOR_OPACITY_DEFAULT = 0.70

/** Runtime boundary for partial/stale Inertia props and range input values. */
export function normalizeFocusIndicatorOpacity(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return FOCUS_INDICATOR_OPACITY_DEFAULT
  }
  return Math.min(FOCUS_INDICATOR_OPACITY_MAX, Math.max(FOCUS_INDICATOR_OPACITY_MIN, value))
}
