// Shared error-message extractor for HTTP composables. Given the `errors`
// map returned by a failed `ApiResult`, resolve a user-visible string:
// prefer a top-level `detail`, else the first flattened value when it is a
// non-empty string, else the caller-supplied `fallback`. NOTE: only the
// FIRST flattened value is examined — an empty first value falls through to
// `fallback` even if a later key holds a non-empty string (behaviour copied
// verbatim from the 12 original composables). Deduplicated from 12 composables
// (feature 0037) — the body is the already-generalized useAnalytics copy.
export function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
  fallback: string,
): string {
  if (!errors) return fallback
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : fallback
}
