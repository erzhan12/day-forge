import { ref } from "vue"
import { router } from "@inertiajs/vue3"
import { type ApiResult, requestJson } from "./useHttp"

interface DraftSubmitResult extends ApiResult {
  explanation?: string | null
}

// Module-level state — Schedule.vue is the sole consumer (single
// instance per page). Mirrors useAI.ts. If a second consumer ever
// appears, move state back into useDraft() to avoid cross-instance
// leakage.
const isGeneratingDraft = ref(false)
const lastDraftError = ref<string | null>(null)

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "Draft generation failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : "Draft generation failed"
}

function statusToMessage(status: number | undefined): string | null {
  switch (status) {
    case 409:
      return "Schedule already has blocks. Clear them before regenerating."
    case 422:
      return "No template configured. Open Settings to create one."
    case 429:
      return "Draft rate limit reached. Try again later."
    case 503:
      return "AI is unavailable. Manual editing still works."
    default:
      return null
  }
}

export function useDraft() {
  async function generateDraft(date: string): Promise<DraftSubmitResult> {
    isGeneratingDraft.value = true
    lastDraftError.value = null

    const result = await requestJson(
      `/api/ai/schedules/${date}/generate-draft/`,
      "POST",
    )

    isGeneratingDraft.value = false

    if (result.ok) {
      const explanation =
        typeof result.data?.explanation === "string"
          ? result.data.explanation
          : null
      // Reload includes ``schedule`` so a future flip on first edit
      // re-renders the badge correctly. ``auto_draft_pending`` is its
      // own Inertia prop, not part of ``schedule``, so this partial
      // reload doesn't refresh it — that's intentional. The
      // per-instance ``attemptedAutoDraftDates`` set in Schedule.vue
      // prevents refire on the same date.
      router.reload({ only: ["blocks", "schedule"] })
      return { ok: true, data: result.data, explanation }
    }

    if (result.status === 409) {
      // Race: schedule already has blocks. Visibility guard upstream
      // should make this nearly impossible; treat as silent no-op.
      return { ok: false, status: 409, errors: result.errors }
    }

    lastDraftError.value =
      statusToMessage(result.status) ?? extractErrorMessage(result.errors)
    return { ok: false, status: result.status, errors: result.errors }
  }

  function clearDraftError() {
    lastDraftError.value = null
  }

  return {
    isGeneratingDraft,
    lastDraftError,
    generateDraft,
    clearDraftError,
  }
}
