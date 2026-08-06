// Only the first flattened value is examined — an empty first value falls through to fallback even if a later key holds a non-empty string.
export function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
  fallback: string,
): string {
  if (!errors) return fallback
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : fallback
}
