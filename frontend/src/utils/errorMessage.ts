// First flattened value only; empty first value falls through to fallback.
export function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
  fallback: string,
): string {
  if (!errors) return fallback
  // A present `detail` wins even when empty (""); it does not fall through to fallback.
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : fallback
}
