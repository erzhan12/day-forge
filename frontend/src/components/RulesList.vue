<script setup lang="ts">
import { ref, watch } from "vue"
import type { Rule } from "../types"
import { useRules } from "../composables/useRules"

const props = defineProps<{
  rules: Rule[]
}>()
const emit = defineEmits<{
  (e: "changed"): void
}>()

const { createRule, updateRule, deleteRule } = useRules()

const newText = ref("")
const newError = ref("")
const submitting = ref(false)

const localRules = ref<Rule[]>(props.rules.map((r) => ({ ...r })))
const editingId = ref<number | null>(null)
const editingText = ref("")
const rowError = ref<{ id: number; message: string } | null>(null)

watch(
  () => props.rules,
  (next) => {
    localRules.value = next.map((r) => ({ ...r }))
    if (editingId.value !== null && !next.find((r) => r.id === editingId.value)) {
      editingId.value = null
    }
    rowError.value = null
  },
  { deep: true },
)

async function addRule() {
  const text = newText.value.trim()
  if (!text) {
    newError.value = "Rule text is required."
    return
  }
  submitting.value = true
  newError.value = ""
  const result = await createRule({ text, is_active: true, priority: 0 })
  submitting.value = false
  if (result.ok) {
    newText.value = ""
    emit("changed")
  } else {
    const errs = result.errors ?? {}
    newError.value =
      Object.values(errs).flat().map(String).join(", ") || "Failed to add rule"
  }
}

function startEdit(rule: Rule) {
  editingId.value = rule.id
  editingText.value = rule.text
}

async function saveEdit(rule: Rule) {
  const text = editingText.value.trim()
  if (!text) {
    rowError.value = { id: rule.id, message: "Text cannot be empty" }
    return
  }
  if (text === rule.text) {
    editingId.value = null
    return
  }
  rowError.value = null
  const result = await updateRule(rule.id, { text })
  if (result.ok) {
    editingId.value = null
    emit("changed")
  } else {
    rowError.value = { id: rule.id, message: "Save failed" }
  }
}

function cancelEdit() {
  editingId.value = null
  rowError.value = null
}

async function toggleActive(rule: Rule) {
  const result = await updateRule(rule.id, { is_active: !rule.is_active })
  if (result.ok) {
    emit("changed")
  } else {
    rowError.value = { id: rule.id, message: "Update failed" }
  }
}

async function bumpPriority(rule: Rule, direction: "up" | "down") {
  const list = [...localRules.value].sort((a, b) => b.priority - a.priority)
  const idx = list.findIndex((r) => r.id === rule.id)
  if (idx === -1) return
  const swapIdx = direction === "up" ? idx - 1 : idx + 1
  if (swapIdx < 0 || swapIdx >= list.length) return
  const neighbour = list[swapIdx]
  if (neighbour.priority === rule.priority) {
    // Same priority — bias by ±1 so a swap actually changes ordering.
    const ruleResult = await updateRule(rule.id, {
      priority: rule.priority + (direction === "up" ? 1 : -1),
    })
    if (ruleResult.ok) emit("changed")
    return
  }
  const ruleResult = await updateRule(rule.id, { priority: neighbour.priority })
  const neighbourResult = await updateRule(neighbour.id, {
    priority: rule.priority,
  })
  if (ruleResult.ok && neighbourResult.ok) {
    emit("changed")
  } else {
    rowError.value = { id: rule.id, message: "Reorder failed" }
  }
}

async function confirmDelete(rule: Rule) {
  if (!window.confirm("Delete this rule?")) return
  const result = await deleteRule(rule.id)
  if (result.ok) {
    emit("changed")
  } else {
    rowError.value = { id: rule.id, message: "Delete failed" }
  }
}
</script>

<template>
  <section class="rules-list">
    <header class="rules-header">
      <h3>Rules</h3>
    </header>

    <form class="add-form" @submit.prevent="addRule">
      <input
        v-model="newText"
        type="text"
        maxlength="500"
        placeholder="e.g. No meetings before 9 AM"
        class="input"
      />
      <button type="submit" class="primary-btn" :disabled="submitting">
        Add rule
      </button>
    </form>
    <p v-if="newError" class="error-text">{{ newError }}</p>

    <ul v-if="localRules.length > 0" class="rules">
      <li v-for="(rule, idx) in localRules" :key="rule.id" class="rule-row">
        <div class="priority-controls">
          <button
            type="button"
            class="arrow-btn"
            :disabled="idx === 0"
            aria-label="Increase priority"
            @click="bumpPriority(rule, 'up')"
          >
            ▲
          </button>
          <button
            type="button"
            class="arrow-btn"
            :disabled="idx === localRules.length - 1"
            aria-label="Decrease priority"
            @click="bumpPriority(rule, 'down')"
          >
            ▼
          </button>
        </div>
        <input
          type="checkbox"
          class="rule-active"
          :checked="rule.is_active"
          aria-label="Active"
          @change="toggleActive(rule)"
        />
        <div v-if="editingId === rule.id" class="rule-edit">
          <input
            v-model="editingText"
            class="input"
            maxlength="500"
            @keydown.enter.prevent="saveEdit(rule)"
            @keydown.escape="cancelEdit"
          />
          <div class="edit-actions">
            <button
              type="button"
              class="primary-btn"
              @click="saveEdit(rule)"
            >
              Save
            </button>
            <button
              type="button"
              class="ghost-btn"
              @click="cancelEdit"
            >
              Cancel
            </button>
          </div>
        </div>
        <button
          v-else
          type="button"
          class="rule-text"
          :class="{ inactive: !rule.is_active }"
          @click="startEdit(rule)"
        >
          {{ rule.text }}
        </button>
        <span class="priority-badge" :title="`Priority ${rule.priority}`">
          {{ rule.priority }}
        </span>
        <button
          type="button"
          class="row-delete-btn"
          aria-label="Delete rule"
          @click="confirmDelete(rule)"
        >
          ×
        </button>
        <p
          v-if="rowError && rowError.id === rule.id"
          class="row-error"
        >
          {{ rowError.message }}
        </p>
      </li>
    </ul>
    <p v-else class="empty-text">No rules yet — add one above.</p>
  </section>
</template>

<style scoped>
.rules-list {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rules-header h3 {
  margin: 0;
  font-size: 16px;
}

.add-form {
  display: flex;
  gap: 8px;
}

.add-form .input {
  flex: 1;
}

.input {
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 14px;
}

.primary-btn {
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
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

.ghost-btn {
  background: white;
  color: #6b7280;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  padding: 8px 16px;
  cursor: pointer;
}

.error-text {
  color: #b91c1c;
  font-size: 13px;
  margin: 0;
}

.rules {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rule-row {
  display: grid;
  grid-template-columns: auto auto 1fr auto auto;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  border-radius: 6px;
}

.rule-row:hover {
  background: #f9fafb;
}

.priority-controls {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.arrow-btn {
  background: transparent;
  border: none;
  color: #6b7280;
  font-size: 11px;
  cursor: pointer;
  padding: 1px 4px;
}

.arrow-btn:hover:not(:disabled) {
  color: #111827;
}

.arrow-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.rule-text {
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  font-size: 14px;
  color: #111827;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: text;
  width: 100%;
}

.rule-text:hover {
  border-color: #d1d5db;
  background: white;
}

.rule-text.inactive {
  text-decoration: line-through;
  color: #9ca3af;
}

.priority-badge {
  font-size: 11px;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 999px;
  padding: 2px 8px;
  min-width: 24px;
  text-align: center;
}

.row-delete-btn {
  background: transparent;
  border: none;
  color: #ef4444;
  font-size: 18px;
  cursor: pointer;
  width: 24px;
  height: 24px;
  border-radius: 6px;
}

.row-delete-btn:hover {
  background: #fee2e2;
}

.rule-edit {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.edit-actions {
  display: flex;
  gap: 6px;
}

.row-error {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 12px;
  color: #b91c1c;
}

.empty-text {
  margin: 0;
  color: #9ca3af;
  font-style: italic;
  font-size: 13px;
}
</style>
