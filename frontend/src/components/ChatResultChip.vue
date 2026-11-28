<script setup lang="ts">
import type { AppliedBlockResult } from "../composables/useChat"

withDefaults(
  defineProps<{
    result?: AppliedBlockResult[]
    showSuggestions?: boolean
    suggestions?: string[]
    disabled?: boolean
    /** Dark 4a phone (feature 0113): one scrolling row of 32px chips. */
    mobile?: boolean
  }>(),
  {
    showSuggestions: false,
    suggestions: () => [],
    disabled: false,
    mobile: false,
  },
)
const emit = defineEmits<{ suggestion: [text: string] }>()
</script>

<template>
  <div
    v-if="result?.length || (showSuggestions && suggestions.length)"
    class="chat-result-chip"
    :class="{ 'chat-result-chip--mobile': mobile }"
    data-testid="chat-result-chip"
  >
    <template v-if="result && result.length">
      <strong>Applied</strong>
      <span v-for="(block, index) in result" :key="index" class="result-row">
        {{ block.change }} · {{ block.start_time }}–{{ block.end_time }} · {{ block.title }}
      </span>
    </template>
    <div v-if="showSuggestions" class="suggestions" aria-label="Suggested AI prompts">
      <button
        v-for="(suggestion, index) in suggestions"
        :key="index"
        type="button"
        :disabled="disabled"
        @pointerdown="mobile && $event.preventDefault()"
        @click="emit('suggestion', suggestion)"
      >
        {{ suggestion }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-result-chip { display:flex; flex-wrap:wrap; align-items:center; gap:5px; margin:4px 0; color:var(--text-primary); font:11px/1.35 var(--font-family-body); }
.result-row { padding:3px 6px; border:1px solid var(--border-strong); border-radius:999px; background:var(--bg-schedule-block); }
.suggestions { display:flex; flex-wrap:wrap; gap:5px; }
button { border:1px solid var(--border-strong); border-radius:999px; background:var(--info-surface); color:oklch(0.78 0.09 230); padding:3px 7px; font:inherit; cursor:pointer; }
button:disabled { cursor:not-allowed; opacity:0.55; }

/* Dark 4a text floor (feature 0106): nothing below 13 px. */
html[data-theme="dark_4a"] .chat-result-chip {
  font-size: 13px;
}

/* Dark 4a phone chip row (feature 0113, SPEC 11.5). pointerdown is cancelled
 * in the template so a tap keeps focus in the chat field and the row stays. */
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .chat-result-chip.chat-result-chip--mobile {
    flex-wrap: nowrap;
    margin: 0;
    padding: 8px 16px 0;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scrollbar-width: none;
  }

  html[data-theme="dark_4a"] .chat-result-chip--mobile .suggestions {
    flex-wrap: nowrap;
    gap: 8px;
  }

  html[data-theme="dark_4a"] .chat-result-chip--mobile .suggestions button {
    flex: 0 0 auto;
    height: 32px;
    padding: 0 12px;
    border: 1px solid #34363B;
    border-radius: 16px;
    background: #232428;
    color: #E5E7EB;
    font-size: 13px;
    font-weight: 500;
    line-height: 1;
    white-space: nowrap;
  }
}
</style>
