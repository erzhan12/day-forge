import { ref } from "vue"
import { router } from "@inertiajs/vue3"
import { type ApiResult, requestJson } from "./useHttp"

// Module-level state — Analytics.vue is the sole consumer (single
// instance per page). Mirrors useDraft.ts. If a second consumer ever
// appears, move state back into useAnalytics() to avoid cross-instance
// leakage.
const isMarkingReviewed = ref(false)
const lastError = ref<string | null>(null)

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
  fallback: string,
): string {
  if (!errors) return fallback
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : fallback
}

export function useAnalytics() {
  async function markReviewed(
    date: string,
    notes?: string,
  ): Promise<ApiResult> {
    isMarkingReviewed.value = true
    lastError.value = null
    const body = notes !== undefined ? { notes } : undefined
    const result = await requestJson(
      `/api/analytics/schedules/${date}/mark-reviewed/`,
      "POST",
      body,
    )
    isMarkingReviewed.value = false

    if (result.ok) {
      // Refresh the review snapshot + status badge. ``blocks`` doesn't
      // change as a result of this call, so we don't include it in the
      // partial reload (matches the granular-reload pattern from
      // useDraft.ts).
      router.reload({ only: ["review", "schedule"] })
      return result
    }
    lastError.value = extractErrorMessage(
      result.errors,
      "Could not mark this day reviewed.",
    )
    return result
  }

  async function saveNotes(
    reviewId: number,
    notes: string,
  ): Promise<ApiResult> {
    // Debounce belongs to the consumer (Analytics.vue); this wrapper
    // just shapes the PATCH payload.
    const result = await requestJson(
      `/api/analytics/reviews/${reviewId}/notes/`,
      "PATCH",
      { notes },
    )
    if (!result.ok) {
      lastError.value = extractErrorMessage(
        result.errors,
        "Could not save notes.",
      )
    }
    return result
  }

  function clearError() {
    lastError.value = null
  }

  return {
    isMarkingReviewed,
    lastError,
    markReviewed,
    saveNotes,
    clearError,
  }
}
