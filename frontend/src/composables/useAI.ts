// @deprecated Use ``useChat`` (composables/useChat.ts) instead — feature
// 0007 replaced the single-shot AI command bar with a multi-turn chat
// dock. This module is kept only so any external import path that still
// references it doesn't break the build; remove once we are confident no
// caller remains. Tests for this composable have been removed.

import { ref } from "vue"
import { router } from "@inertiajs/vue3"
import { type ApiResult, requestJson } from "./useHttp"

interface AISubmitResult extends ApiResult {
  explanation?: string | null
}

// Single module-level state: the command bar is rendered once (see
// CommandBar.vue), so we don't need per-instance refs. This also lets the
// status dot share state across components without prop drilling. Tests
// reset state in `beforeEach` to avoid cross-test leakage — if a second
// consumer is ever added, move this state back into `useAI()`.
const isProcessing = ref(false)
const lastError = ref<string | null>(null)
const lastExplanation = ref<string | null>(null)
const apiHealthy = ref(true)

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "AI command failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : "AI command failed"
}

export function useAI() {
  async function submitCommand(
    date: string,
    command: string,
  ): Promise<AISubmitResult> {
    isProcessing.value = true
    lastError.value = null

    const result = await requestJson(
      `/api/ai/schedules/${date}/command/`,
      "POST",
      { command },
    )

    isProcessing.value = false

    if (result.ok) {
      apiHealthy.value = true
      const explanation =
        typeof result.data?.explanation === "string"
          ? result.data.explanation
          : null
      lastExplanation.value = explanation
      router.reload({ only: ["blocks", "schedule"] })
      return { ok: true, data: result.data, explanation }
    }

    // Network failure from `requestJson` has no status; treat as unhealthy.
    if (
      result.status === undefined ||
      result.status === 502 ||
      result.status === 503 ||
      result.status === 504
    ) {
      apiHealthy.value = false
    }

    lastError.value =
      result.status === 503
        ? "AI is unavailable — manual editing still works."
        : extractErrorMessage(result.errors)
    return { ok: false, errors: result.errors }
  }

  function clearError() {
    lastError.value = null
  }

  return {
    isProcessing,
    lastError,
    lastExplanation,
    apiHealthy,
    submitCommand,
    clearError,
  }
}
