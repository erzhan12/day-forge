<script setup lang="ts">
// Multi-turn AI chat (feature 0007 — bottom dock; feature 0008 — right
// sidebar variant).
//
// One component, two variants:
//   * `variant="dock"`     — fixed bottom dock, dark theme, used on
//     narrow viewports (<1024px).
//   * `variant="sidebar"`  — flex column inside a right-hand sidebar,
//     light theme, used on wide viewports (≥1024px) when the sidebar
//     is open. Larger textarea (min 6 rows, max 20) and unbounded
//     thread history.
//
// State lives in `useChat` (module-level singleton), so the two
// variants share one thread — switching viewports preserves chat.
//
// Keyboard (both variants):
//   * Enter sends the turn
//   * Shift+Enter inserts a newline
//   * Escape clears the input
//   * `/` (when focus is outside form fields) moves focus into the textarea

import type { Ref } from "vue"
import { computed, inject, onMounted, onUnmounted, ref, watch } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useChat } from "../composables/useChat"

type Variant = "dock" | "sidebar"

const props = defineProps<{
  date: string
  snapshotBlocks: () => TimeBlock[]
  pushUndo: (action: UndoAction) => void
  variant: Variant
}>()

const {
  messages,
  isProcessing,
  lastError,
  pendingAsk,
  apiHealthy,
  draftInput,
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

const input = draftInput
const inputEl = ref<HTMLTextAreaElement | null>(null)

const PLACEHOLDERS = [
  "tell me about your day…",
  "опиши свой день — я задам уточняющие вопросы",
  "add standup at 10:00 for 15 min",
]
const placeholder = ref(PLACEHOLDERS[0])
let placeholderTimer: ReturnType<typeof setInterval> | null = null

function isWindowFocused(): boolean {
  return document.visibilityState === "visible" && document.hasFocus()
}

function advancePlaceholder(): void {
  const next = (PLACEHOLDERS.indexOf(placeholder.value) + 1) % PLACEHOLDERS.length
  placeholder.value = PLACEHOLDERS[next]
}

function startPlaceholderRotation(): void {
  if (placeholderTimer) return
  placeholderTimer = setInterval(advancePlaceholder, PLACEHOLDER_ROTATION_MS)
}

function stopPlaceholderRotation(): void {
  if (placeholderTimer) {
    clearInterval(placeholderTimer)
    placeholderTimer = null
  }
}

function syncPlaceholderRotation(): void {
  if (isWindowFocused()) {
    startPlaceholderRotation()
  } else {
    stopPlaceholderRotation()
  }
}

// Tunables. `LINE_HEIGHT_PX` must match the `line-height` rule on
// `.command-input` in <style>; the variant-keyed min/max line counts
// must match the `min-height`/`max-height` rules on the variant-scoped
// `.command-input.variant-*` selectors below — keep JS and CSS in sync.
const DOCK_MAX_VISIBLE_MESSAGES = 4
const LINE_HEIGHT_PX = 20
const PLACEHOLDER_ROTATION_MS = 6_000

const TEXTAREA_LINES: Record<Variant, { min: number; max: number }> = {
  dock: { min: 1, max: 10 },
  sidebar: { min: 6, max: 20 },
}

const textareaMinLines = computed(() => TEXTAREA_LINES[props.variant].min)
const textareaMaxLines = computed(() => TEXTAREA_LINES[props.variant].max)

const visibleMessages = computed(() => {
  const arr = messages.value
  if (props.variant === "dock") {
    return arr.slice(Math.max(0, arr.length - DOCK_MAX_VISIBLE_MESSAGES))
  }
  return arr
})

function autosize(): void {
  const el = inputEl.value
  if (!el) return
  el.style.height = "auto"
  const minHeight = LINE_HEIGHT_PX * textareaMinLines.value
  const maxHeight = LINE_HEIGHT_PX * textareaMaxLines.value
  el.style.height = Math.min(Math.max(el.scrollHeight, minHeight), maxHeight) + "px"
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
  document.addEventListener("visibilitychange", syncPlaceholderRotation)
  window.addEventListener("focus", syncPlaceholderRotation)
  window.addEventListener("blur", syncPlaceholderRotation)
  syncPlaceholderRotation()
  autosize()
})

onUnmounted(() => {
  document.removeEventListener("keydown", handleGlobalKeydown)
  document.removeEventListener("visibilitychange", syncPlaceholderRotation)
  window.removeEventListener("focus", syncPlaceholderRotation)
  window.removeEventListener("blur", syncPlaceholderRotation)
  stopPlaceholderRotation()
})
</script>

<template>
  <div
    class="command-bar"
    :class="`variant-${variant}`"
    data-testid="command-bar"
  >
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
        :rows="textareaMinLines"
        class="command-input"
        :class="`variant-${variant}`"
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
/*
 * CommandBar is intentionally theme-invariant. It is the AI command
 * cockpit — a dark, terminal-style surface that does NOT participate
 * in the Classic / Strategic / Light Premium theme system from
 * feature 0010. The literal dark/blue colors below are deliberate
 * (the chat thread reads like a terminal in every theme), so do NOT
 * convert them to `var(--bg-panel)` / `var(--text-primary)` / etc.
 *
 * Plan §Open technical constraints allowed partial token migration
 * ("Prioritize visible surfaces and interaction states") and this
 * component's "cockpit" aesthetic is the canonical example. If a
 * future product decision is to theme the command bar, that's a
 * separate feature — not a regression of 0010 Phase 6.
 */
.command-bar {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  padding: 8px 16px;
}

/* Dock variant — fixed bottom bar on narrow viewports. */
.command-bar.variant-dock {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  background: #111827;
  color: #e5e7eb;
  border-top: 1px solid #1f2937;
  z-index: 30;
}

/* Sidebar variant — fills the parent (ChatSidebar) as a flex column. */
.command-bar.variant-sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  color: var(--text-primary);
}

.privacy-hint {
  margin: 0 auto 4px;
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
  font-style: italic;
}

.variant-dock .privacy-hint {
  max-width: 640px;
}

.thread {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}

.variant-dock .thread {
  max-width: 640px;
  margin: 0 auto 6px;
  max-height: 200px;
}

.variant-sidebar .thread {
  flex: 1 1 auto;
  min-height: 0;
  margin: 0 0 6px;
}

.bubble {
  font-size: 12px;
  line-height: 1.4;
  padding: 4px 8px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
}

.variant-dock .bubble-user {
  background: #1e3a8a;
  color: #e0e7ff;
}

.variant-dock .bubble-assistant {
  background: #1f2937;
  color: #d1d5db;
}

.variant-sidebar .bubble-user {
  background: #dbeafe;
  color: #1e3a8a;
}

.variant-sidebar .bubble-assistant {
  background: var(--bg-schedule-gap);
  color: var(--text-primary);
}

.bubble-user {
  align-self: flex-end;
  max-width: 85%;
}

.bubble-assistant {
  align-self: flex-start;
  max-width: 85%;
}

.bubble-ask {
  border-left: 2px solid #60a5fa;
}

.command-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.variant-dock .command-row {
  max-width: 640px;
  margin: 0 auto;
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
  font: inherit;
  padding: 6px 0;
  resize: none;
  /* Must equal `LINE_HEIGHT_PX` in <script>; `autosize()` derives the
     bounds as LINE_HEIGHT_PX × {min,max}_TEXTAREA_LINES per variant.
     Pinned to a px value rather than a unitless multiplier so font-size
     changes don't silently break that contract. */
  line-height: 20px;
  overflow-y: auto;
}

.command-input.variant-dock {
  color: #f9fafb;
  min-height: 20px; /* 1 line */
  max-height: 200px; /* 10 lines */
}

.command-input.variant-sidebar {
  color: var(--text-primary);
  min-height: 120px; /* 6 lines */
  max-height: 400px; /* 20 lines */
}

.command-input::placeholder {
  color: var(--text-muted);
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
  color: var(--text-muted);
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
  border-color: var(--text-secondary);
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
  margin: 6px auto 0;
  font-size: 12px;
  padding: 4px 0 0 24px;
  cursor: pointer;
}

.variant-dock .error-row {
  max-width: 640px;
  color: #fca5a5;
}

.variant-sidebar .error-row {
  color: var(--danger-text);
}
</style>
