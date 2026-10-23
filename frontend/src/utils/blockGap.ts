// Keep in sync with templates_mgr/preference_defaults.py.
export const DEFAULT_BLOCK_GAP_MINUTES = 10
export const MIN_BLOCK_GAP_MINUTES = 0
export const MAX_BLOCK_GAP_MINUTES = 120
export const BLOCK_GAP_STEP_MINUTES = 5

export function isValidDefaultBlockGap(raw: unknown): raw is number {
  return typeof raw === "number" && Number.isInteger(raw)
    && raw >= MIN_BLOCK_GAP_MINUTES && raw <= MAX_BLOCK_GAP_MINUTES
    && raw % BLOCK_GAP_STEP_MINUTES === 0
}

export function resolveDefaultBlockGap(raw: unknown): number {
  return isValidDefaultBlockGap(raw) ? raw : DEFAULT_BLOCK_GAP_MINUTES
}
