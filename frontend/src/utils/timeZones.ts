/** Browser timezone helpers: advisory UI input only, never request authority. */
export function browserTimeZone(): string | null {
  try {
    const value = Intl.DateTimeFormat().resolvedOptions().timeZone
    return typeof value === "string" && value ? value : null
  } catch {
    return null
  }
}

export function timeZoneOptions(storedTimeZone = "UTC", detectedTimeZone: string | null = browserTimeZone()): string[] {
  const values = new Set(["UTC", storedTimeZone])
  if (detectedTimeZone) values.add(detectedTimeZone)
  try {
    const supportedValuesOf = (Intl as typeof Intl & {
      supportedValuesOf?: (key: "timeZone") => string[]
    }).supportedValuesOf
    for (const value of supportedValuesOf?.("timeZone") ?? []) values.add(value)
  } catch {
    // Minimal known-valid values retain a functional selector on older browsers.
  }
  return [...values].filter(Boolean).sort((a, b) => a.localeCompare(b))
}
