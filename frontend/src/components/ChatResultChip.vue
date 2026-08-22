<script setup lang="ts">
import type { AppliedBlockResult } from "../composables/useChat"

withDefaults(defineProps<{ result?: AppliedBlockResult[]; showSuggestions?: boolean }>(), { showSuggestions: false })
const emit = defineEmits<{ suggestion: [text: string] }>()

// Deliberately static: prompts are affordances, never an AI response.
const CHAT_SUGGESTIONS = [
  "Plan my remaining day",
  "Add a focused work block",
  "Make room for a break",
] as const
</script>

<template>
  <div class="chat-result-chip" data-testid="chat-result-chip">
    <template v-if="result && result.length">
      <strong>Applied</strong>
      <span v-for="(block, index) in result" :key="index" class="result-row">
        {{ block.change }} · {{ block.start_time }}–{{ block.end_time }} · {{ block.title }}
      </span>
    </template>
    <div v-if="showSuggestions" class="suggestions" aria-label="Suggested AI prompts">
      <button v-for="suggestion in CHAT_SUGGESTIONS" :key="suggestion" type="button" @click="emit('suggestion', suggestion)">{{ suggestion }}</button>
    </div>
  </div>
</template>

<style scoped>
.chat-result-chip { display:flex; flex-wrap:wrap; align-items:center; gap:5px; margin:4px 0; color:var(--text-primary); font:11px/1.35 var(--font-family-body); }
.result-row { padding:3px 6px; border:1px solid var(--border-strong); border-radius:999px; background:var(--bg-schedule-block); }
.suggestions { display:flex; flex-wrap:wrap; gap:5px; }
button { border:1px solid var(--border-strong); border-radius:999px; background:var(--info-surface); color:oklch(0.78 0.09 230); padding:3px 7px; font:inherit; cursor:pointer; }
</style>
