<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue"
import {
  formatDailyExport,
  type DailyExportBlock,
} from "../utils/dailyExport"

const props = defineProps<{
  date: string
  blocks: DailyExportBlock[]
}>()

const emit = defineEmits<{ close: [] }>()

const note = ref("")
const preview = ref("")
const previewElement = ref<HTMLTextAreaElement | null>(null)
const lastGeneratedSnapshot = ref("")
const isDirty = ref(false)
const copyFeedback = ref("")
let feedbackTimer: ReturnType<typeof setTimeout> | null = null
let isMounted = true
let copyAttempt = 0

function generatePreview() {
  const generated = formatDailyExport({
    date: props.date,
    blocks: props.blocks,
    note: note.value,
  })
  preview.value = generated
  lastGeneratedSnapshot.value = generated
}

generatePreview()

watch(note, () => {
  if (!isDirty.value && preview.value === lastGeneratedSnapshot.value) {
    generatePreview()
  }
})

function onPreviewInput() {
  isDirty.value = true
}

function clearFeedbackTimer() {
  if (feedbackTimer) {
    clearTimeout(feedbackTimer)
    feedbackTimer = null
  }
}

function showFeedback(value: string) {
  copyFeedback.value = value
  clearFeedbackTimer()
  feedbackTimer = setTimeout(() => {
    if (isMounted) copyFeedback.value = ""
    feedbackTimer = null
  }, 2000)
}

async function copyPreview() {
  const attempt = ++copyAttempt
  clearFeedbackTimer()
  copyFeedback.value = ""
  try {
    // Deliberately no optional chaining: missing clipboard support must enter
    // the fallback rather than incorrectly reporting a successful copy.
    await navigator.clipboard.writeText(preview.value)
    if (!isMounted || attempt !== copyAttempt) return
    showFeedback("Copied")
  } catch {
    if (!isMounted || attempt !== copyAttempt) return
    previewElement.value?.focus()
    previewElement.value?.select()
    showFeedback("Copy manually with Cmd+C")
  }
}

onUnmounted(() => {
  isMounted = false
  clearFeedbackTimer()
})
</script>

<template>
  <div class="daily-export-backdrop" @click.self="emit('close')">
    <div
      class="daily-export-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="Daily Markdown export"
    >
      <header class="daily-export-header">
        <h3>Daily export</h3>
        <button type="button" class="daily-export-close" aria-label="Close" @click="emit('close')">
          ×
        </button>
      </header>

      <label class="daily-export-field">
        Optional note
        <input v-model="note" class="daily-export-note" maxlength="200" placeholder="Add a note" />
      </label>

      <label class="daily-export-field">
        Markdown preview
        <textarea
          ref="previewElement"
          v-model="preview"
          class="daily-export-preview"
          rows="12"
          @input="onPreviewInput"
        />
      </label>

      <p v-if="copyFeedback" class="daily-export-copy-status" role="status">{{ copyFeedback }}</p>
      <div class="daily-export-actions">
        <button type="button" class="daily-export-copy" @click="copyPreview">Copy</button>
        <button type="button" class="daily-export-cancel" @click="emit('close')">Close</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.daily-export-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.4);
}

.daily-export-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: min(560px, calc(100vw - 32px));
  padding: 16px;
  border-radius: 10px;
  background: var(--bg-panel);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
}

.daily-export-header,
.daily-export-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.daily-export-header h3,
.daily-export-copy-status {
  margin: 0;
  color: var(--text-primary);
}

.daily-export-close,
.daily-export-cancel {
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.daily-export-close {
  width: 28px;
  height: 28px;
  font-size: 20px;
}

.daily-export-field {
  display: grid;
  gap: 5px;
  color: var(--text-primary);
  font-size: 13px;
}

.daily-export-note,
.daily-export-preview {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 8px 10px;
  background: var(--bg-panel);
  color: var(--text-primary);
  font: inherit;
}

.daily-export-preview {
  resize: vertical;
}

.daily-export-copy {
  margin-left: auto;
  border: 1px solid var(--accent-hover);
  border-radius: 6px;
  padding: 6px 14px;
  background: var(--accent-hover);
  color: var(--accent-contrast);
  cursor: pointer;
}

.daily-export-copy-status {
  font-size: 13px;
}
</style>
