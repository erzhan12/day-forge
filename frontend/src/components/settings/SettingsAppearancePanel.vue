<script setup lang="ts">
import { inject, onBeforeUnmount, ref, watch } from "vue"
import { router, usePage } from "@inertiajs/vue3"
import DesignSelector from "../DesignSelector.vue"
import { usePreferences } from "../../composables/usePreferences"
import type { ApiResult } from "../../composables/useHttp"
import { FocusIndicatorControllerKey } from "../../composables/useFocusIndicatorController"
import {
  FOCUS_INDICATOR_OPACITY_DEFAULT,
  FOCUS_INDICATOR_OPACITY_MAX,
  FOCUS_INDICATOR_OPACITY_MIN,
  normalizeFocusIndicatorOpacity,
} from "../../utils/focusIndicatorOpacity"

const page = usePage()
const controller = inject(FocusIndicatorControllerKey, null)
const { saveFocusIndicatorOpacity } = usePreferences()
const opacity = ref(FOCUS_INDICATOR_OPACITY_DEFAULT)
const lastCommitted = ref(FOCUS_INDICATOR_OPACITY_DEFAULT)
const errorMessage = ref("")
const warningMessage = ref("")
let inFlight = false
let queued: number | null = null
let generation = 0
let isMounted = true

function applyPreview(value: number): void {
  opacity.value = value
  controller?.focusIndicator.setOpacity(value)
}

watch(
  () => page.props.ui_preferences?.focus_indicator_opacity,
  (value) => {
    if (value === undefined) return
    const normalized = normalizeFocusIndicatorOpacity(value)
    // A pending local input wins over a stale page prop; a later reload is
    // reconciled by its generation-aware callback below.
    if (!inFlight) {
      lastCommitted.value = normalized
      applyPreview(normalized)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => { isMounted = false })

function settleThenCommitQueued(): void {
  inFlight = false
  const next = queued
  queued = null
  // Never fire a queued commit after unmount — an obsolete panel instance must
  // not issue a stray PATCH that races a freshly mounted settings panel.
  if (next !== null && isMounted) void commit(next)
}

function reconcileAfterReload(sent: number, sentGeneration: number, failed: boolean): void {
  if (!isMounted) return
  if (generation === sentGeneration && opacity.value === sent) {
    // The PATCH we just made is the authoritative account value. A genuinely
    // newer cross-session write is reconciled by the `!inFlight` prop watcher on
    // its next Inertia update, so we do not force the reloaded prop here.
    applyPreview(sent)
  }
  // A successful trailing commit clears any stale error/warning from an earlier
  // failed attempt; a reload failure surfaces only the non-blocking sync warning.
  errorMessage.value = ""
  warningMessage.value = failed ? "Opacity saved. Refresh to fully sync." : ""
}

async function commit(value: number): Promise<void> {
  inFlight = true
  const sentGeneration = generation
  let result: ApiResult
  try {
    result = await saveFocusIndicatorOpacity(value)
  } catch {
    // A thrown save (unexpected transport error) must never strand
    // `inFlight=true`, which would silently stop all further slider
    // persistence. Treat it exactly like a failed save.
    if (!isMounted) return
    if (generation === sentGeneration && opacity.value === value) applyPreview(lastCommitted.value)
    errorMessage.value = "Could not save opacity. Please try again."
    settleThenCommitQueued()
    return
  }
  if (!isMounted) return
  if (!result.ok) {
    if (generation === sentGeneration && opacity.value === value) applyPreview(lastCommitted.value)
    errorMessage.value = (result.errors?.focus_indicator_opacity as string | undefined)
      ?? (result.errors?.body as string | undefined)
      ?? "Could not save opacity. Please try again."
    settleThenCommitQueued()
    return
  }

  // PATCH is committed even if its following partial reload fails; it becomes
  // the rollback baseline for a later failed save.
  lastCommitted.value = value
  let settled = false
  const settle = () => {
    if (settled) return
    settled = true
    settleThenCommitQueued()
  }
  router.reload({
    only: ["ui_preferences"],
    onSuccess: () => { reconcileAfterReload(value, sentGeneration, false) },
    onError: () => { reconcileAfterReload(value, sentGeneration, true) },
    onFinish: settle,
  })
}

function handleInput(event: Event): void {
  const raw = Number((event.target as HTMLInputElement).value)
  const value = normalizeFocusIndicatorOpacity(raw)
  generation++
  errorMessage.value = ""
  warningMessage.value = ""
  applyPreview(value)
  if (inFlight) {
    queued = value
    return
  }
  void commit(value)
}
</script>

<template>
  <section class="settings-panel">
    <h2 id="settings-topic-appearance" class="settings-topic-heading" tabindex="-1">Appearance</h2>
    <DesignSelector />
    <section class="focus-opacity" aria-labelledby="focus-opacity-heading">
      <h3 id="focus-opacity-heading">Focus indicator opacity</h3>
      <label for="focus-indicator-opacity">Content opacity <output aria-live="polite">{{ Math.round(opacity * 100) }}%</output></label>
      <input
        id="focus-indicator-opacity"
        type="range"
        :min="FOCUS_INDICATOR_OPACITY_MIN"
        :max="FOCUS_INDICATOR_OPACITY_MAX"
        step="0.01"
        :value="opacity"
        aria-describedby="focus-opacity-help"
        @input="handleInput"
      >
      <p id="focus-opacity-help">Adjust how faded the Focus indicator appears.</p>
      <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
      <p v-if="warningMessage" role="status">{{ warningMessage }}</p>
    </section>
  </section>
</template>

<style scoped>
.settings-panel { display: flex; flex-direction: column; gap: 16px; }
h2 { margin: 0; color: var(--text-primary); }
h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
</style>
