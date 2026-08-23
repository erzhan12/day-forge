<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { router } from "@inertiajs/vue3"

import { useChatSuggestions } from "../../composables/useChatSuggestions"
import { usePreferences } from "../../composables/usePreferences"
import {
  DEFAULT_CHAT_SUGGESTIONS,
  MAX_CHAT_SUGGESTIONS,
  MAX_CHAT_SUGGESTION_CHARS,
} from "../../utils/chatSuggestions"

interface SuggestionRow {
  id: number
  text: string
}

const suggestions = useChatSuggestions()
const { saveChatSuggestions } = usePreferences()
let nextRowId = 1

function rowsFrom(values: readonly string[]): SuggestionRow[] {
  return values.map((text) => ({ id: nextRowId++, text }))
}

function sameValues(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length
    && left.every((value, index) => value === right[index])
}

const savedSnapshot = ref<string[]>([...suggestions.value])
const rows = ref<SuggestionRow[]>(rowsFrom(savedSnapshot.value))
const isSaving = ref(false)
const errorMessage = ref("")
const statusMessage = ref("")

const draftValues = computed(() => rows.value.map((row) => row.text))
const isDirty = computed(
  () => !sameValues(draftValues.value, savedSnapshot.value),
)

watch(
  suggestions,
  (next) => {
    if (isDirty.value || isSaving.value) return
    savedSnapshot.value = [...next]
    rows.value = rowsFrom(next)
  },
  { deep: true },
)

function addRow(): void {
  if (isSaving.value || rows.value.length >= MAX_CHAT_SUGGESTIONS) return
  rows.value.push({ id: nextRowId++, text: "" })
  errorMessage.value = ""
  statusMessage.value = ""
}

function deleteRow(index: number): void {
  if (isSaving.value) return
  rows.value.splice(index, 1)
  errorMessage.value = ""
  statusMessage.value = ""
}

function moveRow(index: number, offset: -1 | 1): void {
  if (isSaving.value) return
  const target = index + offset
  if (target < 0 || target >= rows.value.length) return
  const [row] = rows.value.splice(index, 1)
  rows.value.splice(target, 0, row)
  statusMessage.value = ""
}

function validatedDraft(): string[] | null {
  if (rows.value.length > MAX_CHAT_SUGGESTIONS) {
    errorMessage.value =
      `Choose ${MAX_CHAT_SUGGESTIONS} suggestions or fewer.`
    return null
  }
  const values: string[] = []
  for (const row of rows.value) {
    const trimmed = row.text.trim()
    if (!trimmed) {
      errorMessage.value = "Suggestions cannot be blank."
      return null
    }
    if ([...trimmed].length > MAX_CHAT_SUGGESTION_CHARS) {
      errorMessage.value =
        `Each suggestion must be ${MAX_CHAT_SUGGESTION_CHARS} characters or fewer.`
      return null
    }
    values.push(trimmed)
  }
  return values
}

function firstError(
  errors: Record<string, string | string[]> | undefined,
  fallback: string,
): string {
  for (const key of ["chat_suggestions", "detail", "body"]) {
    const value = errors?.[key]
    if (typeof value === "string") return value
    if (Array.isArray(value) && value.length) return value.join(" ")
  }
  return fallback
}

async function persist(replacement?: readonly string[]): Promise<void> {
  if (isSaving.value) return
  if (replacement) {
    rows.value = rowsFrom(replacement)
  }
  errorMessage.value = ""
  statusMessage.value = ""
  const payload = validatedDraft()
  if (!payload) return

  isSaving.value = true
  const result = await saveChatSuggestions(payload)
  if (!result.ok) {
    errorMessage.value = firstError(
      result.errors,
      "Could not save suggestions. Please try again.",
    )
    isSaving.value = false
    return
  }

  let reloadHandled = false
  router.reload({
    only: ["ui_preferences"],
    onSuccess: () => {
      reloadHandled = true
      savedSnapshot.value = [...payload]
      rows.value = rowsFrom(payload)
      statusMessage.value = "Suggestions saved."
    },
    onError: (errors) => {
      reloadHandled = true
      errorMessage.value = firstError(
        errors,
        "Suggestions were saved, but the page could not refresh.",
      )
    },
    onFinish: () => {
      if (!reloadHandled) {
        errorMessage.value =
          "Suggestions were saved, but the page could not refresh."
      }
      isSaving.value = false
    },
  })
}

function save(): void {
  void persist()
}

function restoreDefaults(): void {
  void persist([...DEFAULT_CHAT_SUGGESTIONS])
}
</script>

<template>
  <section
    class="suggestions-editor"
    aria-labelledby="chat-suggestions-heading"
    data-testid="settings-ai-chat-suggestions"
  >
    <div class="heading-row">
      <div>
        <h3 id="chat-suggestions-heading">Quick-input suggestions</h3>
        <p class="guidance">
          Up to {{ MAX_CHAT_SUGGESTIONS }} suggestions,
          {{ MAX_CHAT_SUGGESTION_CHARS }} characters each.
        </p>
      </div>
      <button
        type="button"
        class="secondary-button"
        data-testid="add-chat-suggestion"
        :disabled="isSaving || rows.length >= MAX_CHAT_SUGGESTIONS"
        @click="addRow"
      >
        Add suggestion
      </button>
    </div>

    <p class="theme-note">
      These chips currently appear in the <code>dark_4a</code> chat presentation.
    </p>

    <div v-if="rows.length" class="rows">
      <div v-for="(row, index) in rows" :key="row.id" class="suggestion-row">
        <label :for="`chat-suggestion-${row.id}`">Suggestion {{ index + 1 }}</label>
        <div class="row-controls">
          <input
            :id="`chat-suggestion-${row.id}`"
            v-model="row.text"
            type="text"
            :aria-label="`Suggestion ${index + 1}`"
            data-testid="chat-suggestion-input"
            :disabled="isSaving"
            @input="errorMessage = ''; statusMessage = ''"
          >
          <button
            type="button"
            :aria-label="`Move suggestion up ${index + 1}`"
            :disabled="isSaving || index === 0"
            @click="moveRow(index, -1)"
          >↑</button>
          <button
            type="button"
            :aria-label="`Move suggestion down ${index + 1}`"
            :disabled="isSaving || index === rows.length - 1"
            @click="moveRow(index, 1)"
          >↓</button>
          <button
            type="button"
            :aria-label="`Delete suggestion ${index + 1}`"
            :disabled="isSaving"
            @click="deleteRow(index)"
          >Delete</button>
        </div>
      </div>
    </div>
    <p v-else class="empty-note">
      No suggestions will be shown in chat.
    </p>

    <p
      v-if="errorMessage"
      class="feedback error"
      role="alert"
      data-testid="chat-suggestions-error"
    >
      {{ errorMessage }}
    </p>
    <p v-if="statusMessage" class="feedback success" role="status">
      {{ statusMessage }}
    </p>

    <div class="actions">
      <button
        type="button"
        class="primary-button"
        data-testid="save-chat-suggestions"
        :disabled="isSaving || !isDirty"
        @click="save"
      >
        {{ isSaving ? "Saving…" : "Save" }}
      </button>
      <button
        type="button"
        class="secondary-button"
        data-testid="restore-chat-suggestions"
        :disabled="isSaving"
        @click="restoreDefaults"
      >
        Restore defaults
      </button>
    </div>
  </section>
</template>

<style scoped>
.suggestions-editor { display: flex; flex-direction: column; gap: 12px; }
.heading-row { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
h3, p { margin: 0; }
h3 { color: var(--text-primary); font-size: 18px; }
.guidance, .theme-note, .empty-note { color: var(--text-muted); font-size: 13px; }
.theme-note code { color: var(--text-primary); }
.rows { display: flex; flex-direction: column; gap: 10px; }
.suggestion-row { display: flex; flex-direction: column; gap: 5px; }
.suggestion-row label { color: var(--text-muted); font-size: 12px; }
.row-controls { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto; gap: 6px; }
input {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  color: var(--text-primary);
  padding: 9px 10px;
}
button {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-panel);
  color: var(--text-primary);
  padding: 8px 10px;
  cursor: pointer;
}
button:disabled { cursor: not-allowed; opacity: 0.55; }
.primary-button { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast, white); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.feedback { border-radius: var(--radius-sm); font-size: 13px; padding: 8px 10px; }
.error { color: var(--danger-text); background: var(--danger-surface); border: 1px solid var(--danger-border); }
.success { color: var(--text-primary); background: var(--bg-panel); border: 1px solid var(--border); }
@media (max-width: 560px) {
  .heading-row { flex-direction: column; }
  .row-controls { grid-template-columns: 1fr repeat(3, auto); }
}
</style>
