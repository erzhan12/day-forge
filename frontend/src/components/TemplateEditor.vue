<script setup lang="ts">
// TODO(Phase 5+): Drag-and-drop reorder parity with the daily schedule
// is deferred per PRD §7.1 (low-frequency UX, doubles the frontend work
// for templates). Sort order in the rendered list is by start_time
// ascending; the array is sorted client-side before saving.
import { computed, ref, watch } from "vue"
import type { Template, TemplateBlock } from "../types"
import { useTemplates } from "../composables/useTemplates"

const props = defineProps<{
  template: Template | null
  slotType: "weekday" | "weekend"
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
  blocks.value.push({
    title: "",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
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
      <button class="primary-btn" type="button" @click="startCreate">
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
          class="input"
        />
      </label>

      <div class="blocks-section">
        <div class="blocks-header">
          <span>Blocks</span>
          <button type="button" class="add-row-btn" @click="addBlock">
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
                  class="input"
                />
              </td>
              <td>
                <input
                  v-model="b.start_time"
                  type="time"
                  step="300"
                  required
                  class="input"
                />
              </td>
              <td>
                <input
                  v-model="b.end_time"
                  type="time"
                  step="300"
                  required
                  class="input"
                />
              </td>
              <td>
                <select v-model="b.category" class="input">
                  <option value="work">Work</option>
                  <option value="personal">Personal</option>
                  <option value="health">Health</option>
                  <option value="other">Other</option>
                </select>
              </td>
              <td>
                <button
                  type="button"
                  class="row-delete-btn"
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
        <button class="primary-btn" type="submit" :disabled="submitting">
          {{ submitting ? "Saving..." : "Save" }}
        </button>
        <button
          v-if="!isCreate"
          type="button"
          class="danger-btn"
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
  background: white;
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
  color: #111827;
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
  color: #6b7280;
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
  color: #6b7280;
}

.field-label {
  font-weight: 500;
}

.input {
  border: 1px solid #d1d5db;
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
  color: #374151;
}

.add-row-btn {
  font-size: 13px;
  background: white;
  border: 1px solid #d1d5db;
  color: #374151;
  border-radius: 6px;
  padding: 4px 10px;
}

.add-row-btn:hover {
  background: #f9fafb;
}

.blocks-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.blocks-table th {
  text-align: left;
  padding: 4px 6px 6px;
  color: #6b7280;
  font-weight: 500;
  border-bottom: 1px solid #e5e7eb;
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
  color: #9ca3af;
  font-style: italic;
}

.block-errors {
  margin: 4px 0 0;
  padding-left: 18px;
  color: #b91c1c;
  font-size: 12px;
}

.form-actions {
  display: flex;
  gap: 8px;
}

.primary-btn {
  padding: 8px 20px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
}

.primary-btn:hover:not(:disabled) {
  background: #2563eb;
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.danger-btn {
  padding: 8px 20px;
  background: white;
  border: 1px solid #fca5a5;
  color: #b91c1c;
  border-radius: 6px;
  cursor: pointer;
}

.danger-btn:hover:not(:disabled) {
  background: #fee2e2;
}

.error-banner {
  background: #fef2f2;
  color: #b91c1c;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
}
</style>
