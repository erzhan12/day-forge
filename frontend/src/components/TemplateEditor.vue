<script setup lang="ts">
// TODO(Phase 5+): Drag-and-drop reorder parity with the daily schedule
// is deferred per PRD §7.1 (low-frequency UX, doubles the frontend work
// for templates). Sort order in the rendered list is by start_time
// ascending; the array is sorted client-side before saving.
import { computed, ref, watch } from "vue"
import type { Template, TemplateBlock, UserCategory } from "../types"
import { useTemplates } from "../composables/useTemplates"
import { defaultCategory, orderedCategories } from "../utils/categories"

const props = defineProps<{
  template: Template | null
  slotType: "weekday" | "weekend"
  categories?: UserCategory[]
}>()
const emit = defineEmits<{
  (e: "saved"): void
  (e: "deleted"): void
}>()

const { createTemplate, saveTemplate, deleteTemplate } = useTemplates()

const editing = ref(props.template !== null)
const name = ref(props.template?.name ?? "")
const blocks = ref<TemplateBlock[]>(
  props.template ? props.template.blocks.map((b) => ({ ...b })) : [],
)
const errorMessage = ref("")
const blockErrors = ref<string[]>([])
const submitting = ref(false)

watch(
  () => props.template,
  (next) => {
    if (next) {
      editing.value = true
      name.value = next.name
      blocks.value = next.blocks.map((b) => ({ ...b }))
    } else {
      editing.value = false
      name.value = ""
      blocks.value = []
    }
    errorMessage.value = ""
    blockErrors.value = []
  },
  { immediate: false },
)

const isCreate = computed(() => props.template === null)
const slotLabel = computed(() =>
  props.slotType === "weekday" ? "weekday" : "weekend",
)

function startCreate() {
  editing.value = true
  if (!name.value) {
    name.value =
      props.slotType === "weekday" ? "My Weekday" : "My Weekend"
  }
}

function addBlock() {
  const category = defaultCategory(props.categories ?? [])?.slug
  if (!category) {
    errorMessage.value = "Category data could not be loaded. Reload the page and try again."
    return
  }
  blocks.value.push({
    title: "",
    start_time: "09:00",
    end_time: "10:00",
    category,
  })
}

function removeBlock(idx: number) {
  blocks.value.splice(idx, 1)
}

function sortedBlocks(): TemplateBlock[] {
  return [...blocks.value]
    .map((b) => ({ ...b, title: b.title.trim() }))
    .sort((a, b) => a.start_time.localeCompare(b.start_time))
}

function flattenErrors(errors: Record<string, string | string[]> | undefined): {
  text: string
  blockMessages: string[]
} {
  if (!errors) return { text: "Save failed", blockMessages: [] }
  const messages: string[] = []
  let blockMessages: string[] = []
  for (const [key, value] of Object.entries(errors)) {
    if (key === "blocks" && Array.isArray(value)) {
      blockMessages = value as string[]
      messages.push(...(value as string[]))
    } else if (Array.isArray(value)) {
      messages.push(...value.map((v) => String(v)))
    } else {
      messages.push(String(value))
    }
  }
  return {
    text: messages.length > 0 ? messages.join("; ") : "Save failed",
    blockMessages,
  }
}

async function save() {
  if (submitting.value) return
  errorMessage.value = ""
  blockErrors.value = []
  submitting.value = true

  const payload = {
    name: name.value.trim(),
    type: props.slotType,
    blocks: sortedBlocks(),
  }

  const result = isCreate.value
    ? await createTemplate(payload)
    : await saveTemplate(props.template!.id, payload)
  submitting.value = false

  if (result.ok) {
    emit("saved")
    return
  }
  const flat = flattenErrors(result.errors)
  errorMessage.value = flat.text
  blockErrors.value = flat.blockMessages
}

async function confirmDelete() {
  if (!props.template) return
  if (!window.confirm("Delete this template? This cannot be undone.")) return
  submitting.value = true
  const result = await deleteTemplate(props.template.id)
  submitting.value = false
  if (result.ok) {
    emit("deleted")
  } else {
    errorMessage.value = "Delete failed."
  }
}
</script>

<template>
  <section class="template-editor">
    <header class="editor-header">
      <h3>{{ slotLabel === "weekday" ? "Weekday template" : "Weekend template" }}</h3>
      <span class="slot-tag">{{ slotLabel }}</span>
    </header>

    <div v-if="!editing" class="empty-slot">
      <p class="empty-text">No {{ slotLabel }} template yet.</p>
      <button class="primary-btn df-btn df-btn--primary" type="button" @click="startCreate">
        Create template
      </button>
    </div>

    <form v-else class="editor-form" @submit.prevent="save">
      <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>

      <label class="field">
        <span class="field-label">Name</span>
        <input
          v-model="name"
          type="text"
          maxlength="100"
          required
          class="input df-field"
        />
      </label>

      <div class="blocks-section">
        <div class="blocks-header">
          <span>Blocks</span>
          <button type="button" class="add-row-btn df-btn df-btn--field" @click="addBlock">
            + Add block
          </button>
        </div>
        <table v-if="blocks.length > 0" class="blocks-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Start</th>
              <th>End</th>
              <th>Category</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(b, idx) in blocks" :key="idx">
              <td>
                <input
                  v-model="b.title"
                  type="text"
                  maxlength="255"
                  required
                  aria-label="Title"
                  class="input df-field"
                />
              </td>
              <td>
                <input
                  v-model="b.start_time"
                  aria-label="Start"
                  type="time"
                  step="300"
                  required
                  class="input df-field"
                />
              </td>
              <td>
                <input
                  v-model="b.end_time"
                  aria-label="End"
                  type="time"
                  step="300"
                  required
                  class="input df-field"
                />
              </td>
              <td>
                <select v-model="b.category" aria-label="Category" class="input df-field">
                  <option v-for="item in orderedCategories(props.categories ?? [])" :key="item.id" :value="item.slug">{{ item.label }}</option>
                </select>
              </td>
              <td>
                <button
                  type="button"
                  class="row-delete-btn df-btn df-btn--field df-btn--danger"
                  @click="removeBlock(idx)"
                  aria-label="Delete block"
                >
                  ×
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-blocks">
          No blocks yet. Click "Add block" to start.
        </p>
        <ul v-if="blockErrors.length > 0" class="block-errors">
          <li v-for="(msg, i) in blockErrors" :key="i">{{ msg }}</li>
        </ul>
      </div>

      <div class="form-actions">
        <button class="primary-btn df-btn df-btn--primary" type="submit" :disabled="submitting">
          {{ submitting ? "Saving..." : "Save" }}
        </button>
        <button
          v-if="!isCreate"
          type="button"
          class="danger-btn df-btn df-btn--field df-btn--danger"
          :disabled="submitting"
          @click="confirmDelete"
        >
          Delete template
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.template-editor {
  background: var(--bg-panel);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.editor-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.editor-header h3 {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
}

.slot-tag {
  font-size: 11px;
  text-transform: uppercase;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 4px;
  padding: 2px 6px;
}

.empty-slot {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.empty-text {
  margin: 0;
  color: var(--text-muted);
  font-size: 14px;
}

.editor-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.field-label {
  font-weight: 500;
}

.input {
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 14px;
  width: 100%;
  box-sizing: border-box;
}

.blocks-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.blocks-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.add-row-btn {
  font-size: 13px;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  color: var(--text-secondary);
  border-radius: 6px;
  padding: 4px 10px;
}

.add-row-btn:hover {
  background: var(--bg-schedule-gap);
}

.blocks-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.blocks-table th {
  text-align: left;
  padding: 4px 6px 6px;
  color: var(--text-muted);
  font-weight: 500;
  border-bottom: 1px solid var(--border);
}

.blocks-table td {
  padding: 4px 6px;
}

.row-delete-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: #ef4444;
  font-size: 18px;
  cursor: pointer;
  border-radius: 6px;
}

.row-delete-btn:hover {
  background: #fee2e2;
}

.empty-blocks {
  margin: 0;
  font-size: 13px;
  color: var(--text-faint);
  font-style: italic;
}

.block-errors {
  margin: 4px 0 0;
  padding-left: 18px;
  color: var(--danger-text);
  font-size: 12px;
}

.form-actions {
  display: flex;
  gap: 8px;
}

.primary-btn {
  padding: 8px 20px;
  background: var(--accent);
  color: var(--accent-contrast);
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
}

.primary-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.danger-btn {
  padding: 8px 20px;
  background: var(--bg-panel);
  border: 1px solid #fca5a5;
  color: var(--danger-text);
  border-radius: 6px;
  cursor: pointer;
}

.danger-btn:hover:not(:disabled) {
  background: #fee2e2;
}

.error-banner {
  background: var(--danger-surface);
  color: var(--danger-text);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
}

/* Dark 4a (feature 0106): the block-row delete × is a square field button. */
html[data-theme="dark_4a"] .row-delete-btn.df-btn.df-btn {
  width: 36px;
  padding: 0;
}

/* Dark 4a, narrow: five 36 px controls do not fit one table row at 390 px,
   so each block becomes a small grid — title; start and end; category and
   ×. The header row is kept for screen readers only; each input carries
   its own aria-label. */
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .blocks-table,
  html[data-theme="dark_4a"] .blocks-table tbody {
    display: block;
  }

  html[data-theme="dark_4a"] .blocks-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  html[data-theme="dark_4a"] .blocks-table tr {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 36px;
    gap: 6px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
  }

  html[data-theme="dark_4a"] .blocks-table td {
    display: block;
    min-width: 0;
    padding: 0;
  }

  html[data-theme="dark_4a"] .blocks-table td:nth-child(1) { grid-column: 1 / -1; }
  html[data-theme="dark_4a"] .blocks-table td:nth-child(3) { grid-column: 2 / -1; }
  html[data-theme="dark_4a"] .blocks-table td:nth-child(4) { grid-column: 1 / 3; }

  html[data-theme="dark_4a"] .blocks-table .df-field {
    width: 100%;
    min-width: 0;
  }
}

/* Dark 4a text floor (feature 0106): nothing below 13 px. */
html[data-theme="dark_4a"] .slot-tag,
html[data-theme="dark_4a"] .field,
html[data-theme="dark_4a"] .block-errors {
  font-size: 13px;
}
</style>
