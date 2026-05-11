<script setup lang="ts">
// Multi-turn AI chat dock (feature 0007).
//
// Replaces the original single-line `<input>` Phase-4 command bar with a
// chat thread + autogrow `<textarea>`. State lives in `useChat` so the
// future sidebar (PR B) can share the same module-level thread; this
// component renders only when the bottom dock is visible.
//
// Keyboard:
//   * Enter sends the turn
//   * Shift+Enter inserts a newline
//   * Escape clears the input
//   * `/` (when focus is outside form fields) moves focus into the textarea
//
// The latest few messages render above the textarea so the user sees
// the assistant's clarifying questions inline without a sidebar.

import type { Ref } from "vue"
import { computed, inject, onMounted, onUnmounted, ref, watch } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useChat } from "../composables/useChat"

const props = defineProps<{
  date: string
  snapshotBlocks: () => TimeBlock[]
  pushUndo: (action: UndoAction) => void
}>()

const {
  messages,
  isProcessing,
  lastError,
  pendingAsk,
  apiHealthy,
  setActiveDate,
  clearThread,
  submitTurn,
} = useChat()

setActiveDate(props.date)
watch(
  () => props.date,
  (d) => setActiveDate(d),
)

const scheduleDisabled = inject<Ref<boolean> | null>("scheduleDisabled", null)
const inputDisabled = computed(
  () => isProcessing.value || Boolean(scheduleDisabled?.value),
)

const input = ref("")
const inputEl = ref<HTMLTextAreaElement | null>(null)

const PLACEHOLDERS = [
  "tell me about your day…",
  "опиши свой день — я задам уточняющие вопросы",
  "add standup at 10:00 for 15 min",
]
const placeholder = ref(PLACEHOLDERS[0])
let placeholderTimer: ReturnType<typeof setInterval> | null = null

// Tunables for the bottom dock UI. Pulled out as named constants so the
// magic numbers don't drift across handlers — `LINE_HEIGHT_PX` must match
// the `line-height` rule on `.command-input` in <style>; if you change
// one, change the other.
const MAX_VISIBLE_MESSAGES = 4
const LINE_HEIGHT_PX = 20
const MAX_TEXTAREA_LINES = 10
const PLACEHOLDER_ROTATION_MS = 6_000

const visibleMessages = computed(() => {
  const arr = messages.value
  return arr.slice(Math.max(0, arr.length - MAX_VISIBLE_MESSAGES))
})

function autosize(): void {
  const el = inputEl.value
  if (!el) return
  el.style.height = "auto"
  const maxHeight = LINE_HEIGHT_PX * MAX_TEXTAREA_LINES
  el.style.height = Math.min(el.scrollHeight, maxHeight) + "px"
}

async function handleSubmit(): Promise<void> {
  if (inputDisabled.value) return
  const text = input.value.trim()
  if (!text) return
  input.value = ""
  // Reset autogrow after clearing.
  await Promise.resolve()
  autosize()
  try {
    await submitTurn(text, props.snapshotBlocks, props.pushUndo)
  } catch (err) {
    // Errors land inside the thread as a synthetic assistant message —
    // the catch here only matters if `submitTurn` rejects synchronously
    // (e.g. activeDate not set), which Schedule.vue's setActiveDate call
    // makes unreachable in production. Log so a future regression in the
    // Schedule.vue watcher surfaces in the dev console rather than
    // silently dropping the user's input.
    console.error("CommandBar: submitTurn rejected synchronously:", err)
  }
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    handleSubmit()
    return
  }
  if (e.key === "Escape") {
    input.value = ""
    autosize()
    inputEl.value?.blur()
  }
}

function handleInput(): void {
  if (lastError.value) lastError.value = null
  autosize()
}

function handleGlobalKeydown(e: KeyboardEvent): void {
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
  }, PLACEHOLDER_ROTATION_MS)
  autosize()
})

onUnmounted(() => {
  document.removeEventListener("keydown", handleGlobalKeydown)
  if (placeholderTimer) clearInterval(placeholderTimer)
})
</script>

<template>
  <div class="command-bar" data-testid="command-bar">
    <!-- Always visible (not gated on visibleMessages) so the warning
         lands before the user types anything, not after. -->
    <div class="privacy-hint" data-testid="chat-privacy-hint">
      Full chat history is re-sent to the AI provider each turn — clear before discussing sensitive data.
    </div>
    <div v-if="visibleMessages.length > 0" class="thread" data-testid="chat-thread">
      <div
        v-for="(msg, idx) in visibleMessages"
        :key="msg.ts + ':' + idx"
        class="bubble"
        :class="{
          'bubble-user': msg.role === 'user',
          'bubble-assistant': msg.role === 'assistant',
          'bubble-ask':
            msg.role === 'assistant' && pendingAsk && msg.ask === pendingAsk,
        }"
      >
        {{ msg.content }}
      </div>
    </div>
    <form class="command-row" @submit.prevent="handleSubmit">
      <span
        class="status-dot"
        :class="{ healthy: apiHealthy, unhealthy: !apiHealthy }"
        :title="apiHealthy ? 'AI online' : 'AI unavailable'"
      />
      <span class="prompt-marker" aria-hidden="true">›</span>
      <textarea
        ref="inputEl"
        v-model="input"
        rows="1"
        class="command-input"
        :placeholder="placeholder + ' (press / to focus, Shift+Enter for newline)'"
        :disabled="inputDisabled"
        autocomplete="off"
        spellcheck="false"
        data-testid="chat-input"
        @input="handleInput"
        @keydown="handleKeydown"
      />
      <button
        v-if="messages.length > 0"
        type="button"
        class="clear-btn"
        :disabled="Boolean(scheduleDisabled)"
        title="Clear thread"
        data-testid="chat-clear"
        @click="clearThread"
      >
        clear
      </button>
      <span v-if="isProcessing" class="spinner" aria-label="Processing…" />
    </form>
    <div
      v-if="lastError"
      class="error-row"
      role="alert"
      tabindex="0"
      @click="() => (lastError = null)"
      @keydown.enter="() => (lastError = null)"
      @keydown.space.prevent="() => (lastError = null)"
    >
      {{ lastError }}
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

.privacy-hint {
  max-width: 640px;
  margin: 0 auto 4px;
  font-size: 11px;
  color: #6b7280;
  text-align: center;
  font-style: italic;
}

.thread {
  max-width: 640px;
  margin: 0 auto 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}

.bubble {
  font-size: 12px;
  line-height: 1.4;
  padding: 4px 8px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-user {
  background: #1e3a8a;
  color: #e0e7ff;
  align-self: flex-end;
  max-width: 85%;
}

.bubble-assistant {
  background: #1f2937;
  color: #d1d5db;
  align-self: flex-start;
  max-width: 85%;
}

.bubble-ask {
  border-left: 2px solid #60a5fa;
}

.command-row {
  max-width: 640px;
  margin: 0 auto;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 10px;
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
  margin-top: 4px;
}

.command-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #f9fafb;
  font: inherit;
  padding: 6px 0;
  resize: none;
  /* Must equal `LINE_HEIGHT_PX` in <script> — `autosize()` derives the
     max textarea height as LINE_HEIGHT_PX × MAX_TEXTAREA_LINES, so a
     drift between this rule and the constant would mis-size the
     scroll cap. Pinned to a px value rather than a unitless multiplier
     so font-size changes don't silently break that contract. */
  line-height: 20px;
  min-height: 20px;
  max-height: 200px;
  overflow-y: auto;
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

.clear-btn {
  background: transparent;
  color: #6b7280;
  border: 1px solid #374151;
  font: inherit;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 3px;
  cursor: pointer;
  align-self: center;
  flex-shrink: 0;
}

.clear-btn:hover:not(:disabled) {
  color: #d1d5db;
  border-color: #4b5563;
}

.clear-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid #374151;
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
  margin-top: 6px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-row {
  max-width: 640px;
  margin: 6px auto 0;
  font-size: 12px;
  padding: 4px 0 0 24px;
  color: #fca5a5;
  cursor: pointer;
}
</style>
