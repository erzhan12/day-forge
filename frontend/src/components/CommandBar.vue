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
// Both variants use the schedule owner's chat state, so switching
// viewports preserves the thread.
//
// Keyboard (both variants):
//   * Enter sends the turn
//   * Shift+Enter inserts a newline
//   * Escape clears the input
//   * `/` (when focus is outside form fields) moves focus into the textarea

import { computed, inject, nextTick, onMounted, onUnmounted, ref, useId, watch } from "vue"
import { ScheduleDisabledKey } from "../composables/scheduleContext"
import type { UndoAction } from "../types"
import { useChat } from "../composables/useChat"
import { useActiveTheme } from "../composables/useActiveTheme"
import { useChatSuggestions } from "../composables/useChatSuggestions"
import { layoutForTheme } from "../utils/layoutProfile"
import ChatResultChip from "./ChatResultChip.vue"
import BottomSheet from "./BottomSheet.vue"
import { useVisualViewportInset } from "../composables/useVisualViewportInset"

type Variant = "dock" | "sidebar"

const props = defineProps<{
  date: string
  pushUndo: (action: UndoAction) => void
  variant: Variant
  /** A positive value asks for focus once; the owner clears it on focus-handled (0106). */
  focusToken?: number
  /** Dark 4a phone (feature 0113): 52px rest row; chips and a short
   *  disclaimer only while the field is focused; full privacy text behind ⓘ. */
  mobile?: boolean
}>()

const emit = defineEmits<{ "height-change": [height: number]; "focus-handled": [] }>()
const barEl = ref<HTMLElement | null>(null)
let sizeObserver: ResizeObserver | null = null

function reportHeight(): void {
  if (barEl.value) emit("height-change", barEl.value.getBoundingClientRect().height)
}

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
  recoverPending,
  hasPendingRequest,
  pendingRequestText,
  cancelPendingIntent,
  hasPendingIntent,
  discardPending,
} = useChat()

setActiveDate(props.date)
watch(
  () => props.date,
  (d) => setActiveDate(d),
)

const scheduleDisabled = inject(ScheduleDisabledKey, null)
const inputDisabled = computed(
  () => isProcessing.value || Boolean(hasPendingRequest?.value) || Boolean(scheduleDisabled?.value),
)

const confirmDescId = useId()
const confirmingDiscard = ref(false)
const discardBtn = ref<HTMLButtonElement | null>(null)
const keepBtn = ref<HTMLButtonElement | null>(null)
const showDiscard = computed(() => Boolean(hasPendingRequest?.value) && !isProcessing.value)
watch(showDiscard, (visible) => { if (!visible) confirmingDiscard.value = false })

async function askDiscard() {
  confirmingDiscard.value = true
  await nextTick()
  keepBtn.value?.focus()
}
async function keepRequest() {
  confirmingDiscard.value = false
  await nextTick()
  discardBtn.value?.focus()
}
function confirmDiscard() {
  confirmingDiscard.value = false
  discardPending()
}

// The full privacy text stays one string (desktop hint, ⓘ sheet). The phone
// shows the short form above the field while it is focused (ai-safety.md).
const PRIVACY_FULL = "Messages and schedule context may be sent to the AI provider. Clear before discussing sensitive data."
const PRIVACY_SHORT = "Messages may be sent to the AI provider."
const MOBILE_PLACEHOLDER = "Add standup at 10:00 for 15 min"

const expandedEl = ref<HTMLElement | null>(null)
const infoBtn = ref<HTMLButtonElement | null>(null)
const focused = ref(false)
const infoOpen = ref(false)
const keyboardInset = useVisualViewportInset()

function onInputFocus(): void { focused.value = true }
function leavesChat(e: FocusEvent): boolean {
  const next = e.relatedTarget
  return !(next instanceof Node && (expandedEl.value?.contains(next) || inputEl.value === next))
}
function onInputBlur(e: FocusEvent): void { if (leavesChat(e)) focused.value = false }
function onExpandedFocusOut(e: FocusEvent): void { if (leavesChat(e)) focused.value = false }

const input = draftInput
const activeTheme = useActiveTheme()
const is4a = computed(() => layoutForTheme(activeTheme.value) === "4a")
const suggestions = useChatSuggestions()
const inputEl = ref<HTMLTextAreaElement | null>(null)
const statusEl = ref<HTMLElement | null>(null)
const statusText = computed(() =>
  isProcessing.value ? "AI request in progress."
    : hasPendingRequest?.value ? "A previous AI request needs recovery."
      : scheduleDisabled?.value ? "The schedule is busy."
        : "")

// "Plan with AI" (feature 0106): focus the input, or the status region when
// the input is disabled. Read on mount too, because the request can mount a
// collapsed sidebar.
async function honourFocusRequest(token: number | undefined) {
  if (!token) return
  await nextTick()
  if (inputDisabled.value) statusEl.value?.focus()
  else inputEl.value?.focus()
  emit("focus-handled")
}
watch(() => props.focusToken, (token) => { void honourFocusRequest(token) })
onMounted(() => { void honourFocusRequest(props.focusToken) })

const PLACEHOLDERS = [
  "tell me about your day…",
  "опиши свой день — я задам уточняющие вопросы",
  "add standup at 10:00 for 15 min",
]
const placeholder = ref(PLACEHOLDERS[0])
let placeholderTimer: ReturnType<typeof setInterval> | null = null

// visibilityState catches tab switches; hasFocus() catches app/window switches.
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

// The phone rest row has no thread; an open question from the AI still shows.
const showThread = computed(() => !props.mobile || focused.value || Boolean(pendingAsk.value))
const canSend = computed(() => !inputDisabled.value && input.value.trim().length > 0)

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
    await submitTurn(text, props.pushUndo)
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

async function submitSuggestion(text: string): Promise<void> {
  if (inputDisabled.value) return
  input.value = text
  await handleSubmit()
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
  if (props.variant === "dock" && barEl.value) {
    reportHeight()
    if (typeof ResizeObserver !== "undefined") {
      sizeObserver = new ResizeObserver(reportHeight)
      sizeObserver.observe(barEl.value)
    }
  }
})

onUnmounted(() => {
  sizeObserver?.disconnect()
  document.removeEventListener("keydown", handleGlobalKeydown)
  document.removeEventListener("visibilitychange", syncPlaceholderRotation)
  window.removeEventListener("focus", syncPlaceholderRotation)
  window.removeEventListener("blur", syncPlaceholderRotation)
  stopPlaceholderRotation()
})
</script>

<template>
  <div
    ref="barEl"
    class="command-bar"
    :class="[`variant-${variant}`, { 'command-bar--mobile': mobile }]"
    :style="mobile ? { bottom: `${keyboardInset}px` } : undefined"
    data-testid="command-bar"
  >
    <!-- Always visible (not gated on visibleMessages) so the warning
         lands before the user types anything, not after. On the phone the
         full text moves behind ⓘ and a short form shows while focused. -->
    <div v-if="!mobile" class="privacy-hint" data-testid="chat-privacy-hint">{{ PRIVACY_FULL }}</div>
    <div v-if="visibleMessages.length > 0 && showThread" class="thread" data-testid="chat-thread">
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
          <ChatResultChip
            v-if="is4a && msg.role === 'assistant' && msg.appliedResult"
            :result="msg.appliedResult"
          />
        </div>
    </div>
    <div v-if="mobile && focused" ref="expandedEl" class="chat-expanded" @focusout="onExpandedFocusOut">
      <ChatResultChip
        v-if="is4a && suggestions.length > 0"
        show-suggestions
        mobile
        :suggestions="suggestions"
        :disabled="inputDisabled"
        @suggestion="(text: string) => void submitSuggestion(text)"
      />
      <p class="privacy-hint-short" data-testid="chat-privacy-hint-short">{{ PRIVACY_SHORT }}</p>
    </div>
    <ChatResultChip
      v-else-if="!mobile && is4a && suggestions.length > 0"
      show-suggestions
      :suggestions="suggestions"
      :disabled="inputDisabled"
      @suggestion="(text: string) => void submitSuggestion(text)"
    />
    <p v-if="hasPendingRequest && !isProcessing" class="recovery-request">Previous request: {{ pendingRequestText }}</p>
    <button
      v-if="hasPendingRequest && !isProcessing"
      type="button"
      :disabled="Boolean(scheduleDisabled)"
      data-testid="chat-recover"
      class="recover-btn"
      @click="recoverPending(props.pushUndo)"
      title="Return the saved result, or finish the original request if needed."
    >Recover previous AI request</button>
    <button
      v-if="showDiscard && !confirmingDiscard"
      ref="discardBtn"
      type="button"
      data-testid="chat-discard"
      class="recover-btn"
      @click="askDiscard"
    >Discard request</button>
    <div v-if="showDiscard && confirmingDiscard" class="discard-confirm" role="alertdialog" aria-label="Discard unconfirmed AI request" :aria-describedby="confirmDescId">
      <p :id="confirmDescId" data-testid="chat-discard-warning">The original request may already have been applied. Check the schedule before retrying.</p>
      <button type="button" ref="keepBtn" class="recover-btn" data-testid="chat-discard-cancel" @click="keepRequest">Keep</button>
      <button type="button" class="recover-btn" data-testid="chat-discard-confirm" @click="confirmDiscard">Discard anyway</button>
    </div>
    <button
      v-if="hasPendingIntent"
      type="button"
      class="recover-btn"
      data-testid="chat-cancel-intent"
      :disabled="inputDisabled"
      @click="cancelPendingIntent(props.pushUndo)"
    >Cancel clarification</button>
    <p
      ref="statusEl"
      class="chat-status-sr"
      role="status"
      tabindex="-1"
      data-testid="chat-status"
    >{{ statusText }}</p>
    <form class="command-row" @submit.prevent="handleSubmit">
      <button
        v-if="mobile"
        ref="infoBtn"
        type="button"
        class="info-btn"
        aria-label="About AI privacy"
        aria-haspopup="dialog"
        data-testid="chat-privacy-info"
        @pointerdown.prevent
        @click="infoOpen = true"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9.5" />
          <path d="M12 11v5.5M12 7.6v.1" />
        </svg>
      </button>
      <span
        v-if="!mobile"
        class="status-dot"
        :class="{ healthy: apiHealthy, unhealthy: !apiHealthy }"
        :title="apiHealthy ? 'AI online' : 'AI unavailable'"
      />
      <span v-if="!mobile" class="prompt-marker" aria-hidden="true">›</span>
      <textarea
        ref="inputEl"
        v-model="input"
        :rows="textareaMinLines"
        class="command-input"
        :class="`variant-${variant}`"
        :placeholder="mobile ? MOBILE_PLACEHOLDER : placeholder + ' (press / to focus, Shift+Enter for newline)'"
        :disabled="inputDisabled"
        autocomplete="off"
        spellcheck="false"
        data-testid="chat-input"
        @input="handleInput"
        @keydown="handleKeydown"
        @focus="onInputFocus"
        @blur="onInputBlur"
      />
      <button
        v-if="messages.length > 0 && (!mobile || focused)"
        type="button"
        class="clear-btn"
        @pointerdown="mobile && $event.preventDefault()"
        :disabled="!isProcessing && (Boolean(scheduleDisabled) || Boolean(hasPendingRequest))"
        title="Clear thread"
        data-testid="chat-clear"
        @click="clearThread"
      >
        clear
      </button>
      <span v-if="isProcessing" class="spinner" aria-label="Processing…" />
      <button
        v-if="mobile"
        type="submit"
        class="send-btn"
        :class="{ 'send-btn--ready': canSend }"
        :aria-disabled="!canSend"
        aria-label="Send"
        data-testid="chat-send"
        @pointerdown.prevent
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
        </svg>
      </button>
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
    <BottomSheet
      v-if="mobile && infoOpen"
      title="AI privacy"
      :fallback-focus="() => infoBtn"
      @close="infoOpen = false"
    >
      <p class="privacy-full" data-testid="chat-privacy-full">{{ PRIVACY_FULL }}</p>
    </BottomSheet>
  </div>
</template>

<style scoped>
.recovery-request {
  margin: 8px 0;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.recover-btn {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-panel);
  color: var(--text-primary);
  cursor: pointer;
}

.discard-confirm {
  margin: 8px 0;
  font-size: 12px;
}

.discard-confirm p {
  margin: 0 0 6px;
}

.discard-confirm .recover-btn + .recover-btn {
  margin-left: 6px;
}

.recover-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
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
 *
 * Exception — Dark 4a (feature 0106): the html[data-theme="dark_4a"]
 * rules at the end of this block theme the dock surface and switch the
 * input to the body font at 14 px (16 px on coarse pointers) with
 * --text-secondary text and placeholder; the bubbles, privacy hint, Clear
 * and error text go to 13 px. The transcript keeps its monospace font,
 * and line-height stays 20px to match LINE_HEIGHT_PX.
 */
.chat-status-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

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

html[data-theme="dark_4a"] .command-bar.variant-dock {
  background: var(--bg-panel);
  color: var(--text-primary);
  border-color: var(--border);
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

/* Dark 4a chat input (feature 0106): both variants. */
html[data-theme="dark_4a"] .command-input.command-input {
  font-family: var(--font-family-body);
  font-size: 14px;
  line-height: 20px;
  color: var(--text-secondary);
}

html[data-theme="dark_4a"] .command-input::placeholder {
  font-family: var(--font-family-body);
  color: var(--text-secondary);
  opacity: 1;
}

html[data-theme="dark_4a"] .privacy-hint,
html[data-theme="dark_4a"] .bubble,
html[data-theme="dark_4a"] .clear-btn,
html[data-theme="dark_4a"] .error-row,
html[data-theme="dark_4a"] .recovery-request,
html[data-theme="dark_4a"] .discard-confirm {
  font-size: 13px;
}

@media (pointer: coarse) {
  /* 16 px stops iOS zoom-on-focus (plan question 7). */
  html[data-theme="dark_4a"] .command-input.command-input {
    font-size: 16px;
  }
}

/* Dark 4a phone chat (feature 0113, SPEC 11.5). Rest: one 52px row plus the
 * home-indicator inset. Focused: chips and a one-line disclaimer above the
 * field. The panel rides above the keyboard through the visual viewport inset
 * set inline on the root. Panel/chip hexes are the mentor spec's, with no
 * app.css token of the same value. */
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .command-bar.command-bar--mobile.variant-dock {
    padding: 0 0 var(--safe-bottom);
    background: #1F2023;
    border-top: 1px solid #34363B;
    font-family: var(--font-family-body);
  }

  html[data-theme="dark_4a"] .command-bar--mobile .command-row {
    max-width: none;
    margin: 0;
    padding: 0 12px 0 6px;
    min-height: 52px;
    align-items: center;
    gap: 8px;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .info-btn {
    flex: 0 0 auto;
    width: 44px;
    height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .command-input.command-input {
    box-sizing: border-box;
    min-height: 36px;
    max-height: 96px;
    padding: 8px 12px;
    border: 1px solid var(--border-control);
    border-radius: 12px;
    background: var(--bg-page);
    color: #E5E7EB;
    font-size: 16px;
    font-weight: 400;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .command-input:focus {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
    border-radius: 12px;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .send-btn {
    flex: 0 0 auto;
    width: 36px;
    height: 36px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: #2A2C31;
    color: var(--text-secondary);
    cursor: default;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .send-btn.send-btn--ready {
    background: var(--accent);
    color: var(--accent-contrast);
    cursor: pointer;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .privacy-hint-short {
    margin: 0;
    padding: 6px 16px 0;
    font-size: 13px;
    font-weight: 400;
    line-height: 18px;
    color: var(--text-secondary);
  }

  html[data-theme="dark_4a"] .command-bar--mobile .thread {
    max-width: none;
    margin: 0;
    padding: 8px 16px 0;
    max-height: 30dvh;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .clear-btn {
    min-height: 36px;
    padding: 0 8px;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .error-row,
  html[data-theme="dark_4a"] .command-bar--mobile .recovery-request,
  html[data-theme="dark_4a"] .command-bar--mobile .discard-confirm {
    max-width: none;
    margin: 0;
    padding: 8px 16px;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .spinner {
    margin-top: 0;
  }

  html[data-theme="dark_4a"] .command-bar--mobile .privacy-full {
    margin: 0;
    font-size: 14px;
    line-height: 20px;
    color: var(--text-primary);
  }
}
</style>
