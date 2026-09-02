const KEY = "day-forge:focus-indicator:should-be-open"
let memoryValue = false

/** Safe, strict device-local restore intent. Storage is an enhancement only. */
export function readFocusIndicatorShouldBeOpen(): boolean {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw === null) return memoryValue
    // A present-but-malformed payload is a strict `false`, not the prior
    // in-memory intent — only a genuine storage-access failure (getItem throw)
    // falls back to current-tab memory.
    try {
      return JSON.parse(raw) === true
    } catch {
      return false
    }
  } catch {
    return memoryValue
  }
}

export function writeFocusIndicatorShouldBeOpen(value: boolean): void {
  memoryValue = value === true
  try { localStorage.setItem(KEY, JSON.stringify(memoryValue)) } catch { /* safe fallback */ }
}

export function clearFocusIndicatorShouldBeOpen(): void {
  memoryValue = false
  try {
    localStorage.removeItem(KEY)
  } catch {
    // If removal fails, overwrite with an explicit `false` so a stale `true`
    // can never be read back as authoritative after an explicit close/logout.
    try { localStorage.setItem(KEY, "false") } catch { /* memory-only fallback */ }
  }
}
