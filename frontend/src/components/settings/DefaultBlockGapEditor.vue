<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue"
import { router, usePage } from "@inertiajs/vue3"
import type { UiPreferences } from "../../types"
import { usePreferences } from "../../composables/usePreferences"
import {
  BLOCK_GAP_STEP_MINUTES,
  MAX_BLOCK_GAP_MINUTES,
  MIN_BLOCK_GAP_MINUTES,
  isValidDefaultBlockGap,
  resolveDefaultBlockGap,
} from "../../utils/blockGap"

const page = usePage()
const accepted = computed(() => resolveDefaultBlockGap(
  (page.props?.ui_preferences as UiPreferences | undefined)?.default_block_gap_minutes,
))
const draft = ref<number | string>(accepted.value)
const saving = ref(false)
const errorMessage = ref("")
const statusMessage = ref("")
const { saveDefaultBlockGap } = usePreferences()
let mounted = true
onUnmounted(() => { mounted = false })
watch(accepted, (value) => { draft.value = value })

function validate(): number | null {
  const value = typeof draft.value === "number" ? draft.value : (
    draft.value.trim() ? Number(draft.value) : NaN
  )
  if (!isValidDefaultBlockGap(value)) {
    errorMessage.value = "Choose an integer from 0 to 120 minutes in 5-minute increments."
    return null
  }
  return value
}

function firstError(errors: Record<string, string | string[]> | undefined): string {
  for (const key of ["default_block_gap_minutes", "detail", "body"]) {
    const value = errors?.[key]
    if (typeof value === "string") return value
    if (Array.isArray(value) && value.length) return value.join(" ")
  }
  return "Could not save the default gap. Please try again."
}

async function save(): Promise<void> {
  if (saving.value) return
  errorMessage.value = ""
  statusMessage.value = ""
  const value = validate()
  if (value === null) return
  saving.value = true
  const result = await saveDefaultBlockGap(value)
  if (!mounted) return
  if (!result.ok) {
    errorMessage.value = firstError(result.errors)
    saving.value = false
    return
  }

  let reloadHandled = false
  const refreshError = "Default gap was saved, but the page could not refresh."
  router.reload({
    only: ["ui_preferences"],
    onSuccess: () => {
      reloadHandled = true
      if (!mounted) return
      draft.value = accepted.value
      statusMessage.value = "Default gap saved."
    },
    onError: () => {
      reloadHandled = true
      if (!mounted) return
      errorMessage.value = refreshError
    },
    onFinish: () => {
      if (!mounted) return
      if (!reloadHandled) errorMessage.value = refreshError
      saving.value = false
    },
  })
}
</script>

<template>
  <section class="gap-editor" aria-label="Default gap between blocks">
    <div class="inputs">
      <label for="default-block-gap">Default gap between blocks (minutes)
        <input
          id="default-block-gap"
          v-model="draft"
          type="number"
          :min="MIN_BLOCK_GAP_MINUTES"
          :max="MAX_BLOCK_GAP_MINUTES"
          :step="BLOCK_GAP_STEP_MINUTES"
          :disabled="saving"
          :aria-invalid="!!errorMessage"
          aria-describedby="default-block-gap-help default-block-gap-feedback"
          @input="errorMessage = ''; statusMessage = ''"
        >
      </label>
      <button type="button" :disabled="saving" @click="save">{{ saving ? "Saving…" : "Save" }}</button>
    </div>
    <p id="default-block-gap-help" class="help">
      Prefer this gap before and after blocks added through chat without a start time.
      Choose 0–120 minutes in 5-minute steps; 0 allows back-to-back blocks.
      The gap may shrink in 5-minute steps to fit the initial free window.
      Later windows retain the full configured gap. Explicit times and requested gaps
      take precedence. Existing blocks are not moved.
      Current preference: {{ accepted }} minutes.
    </p>
    <div id="default-block-gap-feedback">
      <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
      <p v-if="statusMessage" role="status">{{ statusMessage }}</p>
    </div>
  </section>
</template>

<style scoped>
.gap-editor { display: flex; flex-direction: column; gap: 8px; }
.inputs { display: flex; gap: 10px; align-items: end; flex-wrap: wrap; }
label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
input, button { padding: 6px 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--bg-page); color: var(--text-primary); }
input { min-width: 0; max-width: 100%; }
button { cursor: pointer; background: var(--accent); color: var(--accent-contrast, white); }
button:disabled { cursor: not-allowed; opacity: 0.55; }
p { margin: 0; font-size: 13px; overflow-wrap: anywhere; }
.help { color: var(--text-muted); }
.error { color: var(--danger-text); }
</style>
