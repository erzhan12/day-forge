<script setup lang="ts">
// This component is the sole consumer of `useAI` — that composable holds
// module-level state (isProcessing, lastError, lastExplanation,
// apiHealthy) so the status dot can share state without prop-drilling.
// If a second consumer is ever added (e.g. a chat drawer), move that
// state back into `useAI()` to avoid cross-instance leakage.
import type { Ref } from "vue"
import { computed, inject, onMounted, onUnmounted, ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useAI } from "../composables/useAI"

const props = defineProps<{
  date: string
  snapshotBlocks: () => TimeBlock[]
  pushUndo: (action: UndoAction) => void
}>()

const {
  isProcessing, lastError, lastExplanation, apiHealthy,
  submitCommand, clearError,
} = useAI()

const scheduleDisabled = inject<Ref<boolean> | null>("scheduleDisabled", null)
const inputDisabled = computed(
  () => isProcessing.value || Boolean(scheduleDisabled?.value),
)

const input = ref("")
const inputEl = ref<HTMLInputElement | null>(null)

const PLACEHOLDERS = [
  "add standup at 10:00 for 15 min",
  "добавь звонок в 10 на 30 минут",
  "move gym to 18:00",
]
const placeholder = ref(PLACEHOLDERS[0])
let placeholderTimer: ReturnType<typeof setInterval> | null = null

function _scheduleChanged(snapshot: TimeBlock[], responseBlocks: unknown): boolean {
  if (!Array.isArray(responseBlocks)) return false
  const key = (b: TimeBlock) =>
    `${b.id}|${b.title}|${b.start_time}|${b.end_time}|${b.category}|${b.is_completed}|${b.sort_order}`
  const before = new Set(snapshot.map(key))
  const after = new Set((responseBlocks as TimeBlock[]).map((b) => key(b as TimeBlock)))
  if (before.size !== after.size) return true
  for (const k of before) if (!after.has(k)) return true
  return false
}

async function handleSubmit() {
  if (inputDisabled.value) return
  const command = input.value.trim()
  if (!command) return

  const snapshot = props.snapshotBlocks()
  const result = await submitCommand(props.date, command)

  if (result.ok) {
    if (_scheduleChanged(snapshot, result.data?.blocks)) {
      props.pushUndo({
        description: result.explanation || "AI command",
        type: "ai",
        previousBlocks: snapshot,
        scheduleDate: props.date,
      })
    }
    input.value = ""
  }
  // On failure: keep input so the user can edit and retry.
}

function handleInput() {
  if (lastError.value) clearError()
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    input.value = ""
    clearError()
    inputEl.value?.blur()
  }
}

function handleGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== "/") return
  // Same guard as useUndo.ts: ignore while the user is typing elsewhere.
  const target = e.target as HTMLElement | null
  const tag = target?.tagName?.toLowerCase()
  if (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    target?.isContentEditable
  ) {
    return
  }
  e.preventDefault()
  inputEl.value?.focus()
}

onMounted(() => {
  document.addEventListener("keydown", handleGlobalKeydown)
  placeholderTimer = setInterval(() => {
    const next = (PLACEHOLDERS.indexOf(placeholder.value) + 1) % PLACEHOLDERS.length
    placeholder.value = PLACEHOLDERS[next]
  }, 4_000)
})

onUnmounted(() => {
  document.removeEventListener("keydown", handleGlobalKeydown)
  if (placeholderTimer) clearInterval(placeholderTimer)
})
</script>

<template>
  <div class="command-bar">
    <form class="command-row" @submit.prevent="handleSubmit">
      <span
        class="status-dot"
        :class="{ healthy: apiHealthy, unhealthy: !apiHealthy }"
        :title="apiHealthy ? 'AI online' : 'AI unavailable'"
      />
      <span class="prompt-marker" aria-hidden="true">›</span>
      <input
        ref="inputEl"
        v-model="input"
        type="text"
        class="command-input"
        :placeholder="placeholder + ' (press / to focus)'"
        :disabled="inputDisabled"
        autocomplete="off"
        spellcheck="false"
        @input="handleInput"
        @keydown="handleKeydown"
      />
      <span v-if="isProcessing" class="spinner" aria-label="Processing…" />
    </form>
    <div
      v-if="lastError"
      class="error-row"
      role="alert"
      tabindex="0"
      @click="clearError"
      @keydown.enter="clearError"
      @keydown.space.prevent="clearError"
    >
      {{ lastError }}
    </div>
    <div v-else-if="lastExplanation" class="explanation-row">
      {{ lastExplanation }}
    </div>
  </div>
</template>

<style scoped>
.command-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  background: #111827;
  color: #e5e7eb;
  border-top: 1px solid #1f2937;
  z-index: 30;
  padding: 8px 16px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.command-row {
  max-width: 640px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.healthy {
  background: #10b981;
  box-shadow: 0 0 4px #10b981;
}

.status-dot.unhealthy {
  background: #ef4444;
  box-shadow: 0 0 4px #ef4444;
}

.prompt-marker {
  color: #60a5fa;
  font-weight: 600;
  flex-shrink: 0;
}

.command-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #f9fafb;
  font: inherit;
  padding: 6px 0;
}

.command-input::placeholder {
  color: #6b7280;
}

.command-input:focus {
  outline: 1px solid #3b82f6;
  outline-offset: 2px;
  border-radius: 2px;
}

.command-input:disabled {
  opacity: 0.6;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #374151;
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-row,
.explanation-row {
  max-width: 640px;
  margin: 6px auto 0;
  font-size: 12px;
  padding: 4px 0 0 24px;
}

.error-row {
  color: #fca5a5;
  cursor: pointer;
}

.explanation-row {
  color: #9ca3af;
}
</style>
