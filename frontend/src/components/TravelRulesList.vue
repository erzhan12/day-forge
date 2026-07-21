<script setup lang="ts">
import { ref, watch } from "vue"
import type { TravelRule } from "../types"
import { useTravelRules } from "../composables/useTravelRules"

const MAX_TRAVEL_MINUTES = 600

const props = defineProps<{
  rules: TravelRule[]
}>()
const emit = defineEmits<{
  (e: "changed"): void
}>()

const { createRule, updateRule, deleteRule } = useTravelRules()

const newKeyword = ref("")
const newThere = ref(0)
const newBack = ref(0)
const newCategory = ref<TravelRule["category"]>("")
const newError = ref("")
const submitting = ref(false)

const localRules = ref<TravelRule[]>(props.rules.map((r) => ({ ...r })))
const editingId = ref<number | null>(null)
const editKeyword = ref("")
const editThere = ref(0)
const editBack = ref(0)
const editCategory = ref<TravelRule["category"]>("")
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

// Reject NaN and clamp to the same 0..600 cap the backend enforces so a
// wild number input can't produce a 400 round-trip.
function clampMinutes(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(MAX_TRAVEL_MINUTES, Math.round(value)))
}

async function addRule() {
  const keyword = newKeyword.value.trim()
  if (!keyword) {
    newError.value = "Keyword is required."
    return
  }
  submitting.value = true
  newError.value = ""
  const result = await createRule({
    keyword,
    travel_there_minutes: clampMinutes(newThere.value),
    travel_back_minutes: clampMinutes(newBack.value),
    category: newCategory.value,
  })
  submitting.value = false
  if (result.ok) {
    newKeyword.value = ""
    newThere.value = 0
    newBack.value = 0
    newCategory.value = ""
    emit("changed")
  } else {
    const errs = result.errors ?? {}
    newError.value =
      Object.values(errs).flat().map(String).join(", ") ||
      "Failed to add travel rule"
  }
}

function startEdit(rule: TravelRule) {
  editingId.value = rule.id
  editKeyword.value = rule.keyword
  editThere.value = rule.travel_there_minutes
  editBack.value = rule.travel_back_minutes
  editCategory.value = rule.category
}

async function saveEdit(rule: TravelRule) {
  const keyword = editKeyword.value.trim()
  if (!keyword) {
    rowError.value = { id: rule.id, message: "Keyword cannot be empty" }
    return
  }
  rowError.value = null
  const result = await updateRule(rule.id, {
    keyword,
    travel_there_minutes: clampMinutes(editThere.value),
    travel_back_minutes: clampMinutes(editBack.value),
    category: editCategory.value,
  })
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

// Ascending `order`, top row = first match. DIRECTION FLIP vs
// RulesList.bumpPriority: there "up" means a higher priority number; here
// "up" must DECREASE `order` (swap with the previous row's value) so the
// row moves toward the top and wins matching earlier.
async function bumpOrder(rule: TravelRule, direction: "up" | "down") {
  const list = [...localRules.value].sort(
    (a, b) => a.order - b.order || a.id - b.id,
  )
  const idx = list.findIndex((r) => r.id === rule.id)
  if (idx === -1) return
  const swapIdx = direction === "up" ? idx - 1 : idx + 1
  if (swapIdx < 0 || swapIdx >= list.length) return
  const neighbour = list[swapIdx]
  if (neighbour.order === rule.order) {
    // Same order (legacy rows) — bias by ∓1 so the swap actually reorders.
    const result = await updateRule(rule.id, {
      order: rule.order + (direction === "up" ? -1 : 1),
    })
    if (result.ok) {
      emit("changed")
    } else {
      // Without this the arrow is a silent no-op when the bias lands outside
      // the API's accepted order range (rows already at a bound).
      rowError.value = { id: rule.id, message: "Reorder failed" }
    }
    return
  }
  const ruleResult = await updateRule(rule.id, { order: neighbour.order })
  const neighbourResult = await updateRule(neighbour.id, { order: rule.order })
  if (ruleResult.ok && neighbourResult.ok) {
    emit("changed")
  } else {
    rowError.value = { id: rule.id, message: "Reorder failed" }
  }
}

async function confirmDelete(rule: TravelRule) {
  if (!window.confirm("Delete this travel rule?")) return
  const result = await deleteRule(rule.id)
  if (result.ok) {
    emit("changed")
  } else {
    rowError.value = { id: rule.id, message: "Delete failed" }
  }
}

function categoryLabel(category: TravelRule["category"]): string {
  return category === "" ? "other (default)" : category
}
</script>

<template>
  <section class="travel-rules-list">
    <!-- No internal heading: Settings.vue owns the "Travel-time rules"
         subsection-title, matching the Apple/Google Calendar subsections
         this list sits among. -->
    <p class="hint-text">
      When an event title contains the keyword, "Add to schedule" prefills
      these travel minutes. Top rule wins on multiple matches.
    </p>

    <form class="add-form" @submit.prevent="addRule">
      <input
        v-model="newKeyword"
        type="text"
        maxlength="100"
        placeholder="Title keyword, e.g. dentist"
        class="input keyword-input"
      />
      <label class="minutes-field">
        There
        <input
          v-model.number="newThere"
          type="number"
          min="0"
          :max="MAX_TRAVEL_MINUTES"
          class="input minutes-input"
        />
      </label>
      <label class="minutes-field">
        Back
        <input
          v-model.number="newBack"
          type="number"
          min="0"
          :max="MAX_TRAVEL_MINUTES"
          class="input minutes-input"
        />
      </label>
      <select v-model="newCategory" class="input" aria-label="Category">
        <option value="">other (default)</option>
        <option value="work">work</option>
        <option value="personal">personal</option>
        <option value="health">health</option>
        <option value="other">other</option>
      </select>
      <button type="submit" class="primary-btn" :disabled="submitting">
        Add rule
      </button>
    </form>
    <p v-if="newError" class="error-text">{{ newError }}</p>

    <ul v-if="localRules.length > 0" class="rules">
      <li v-for="(rule, idx) in localRules" :key="rule.id" class="rule-row">
        <div class="order-controls">
          <button
            type="button"
            class="arrow-btn"
            :disabled="idx === 0"
            aria-label="Move up (match earlier)"
            @click="bumpOrder(rule, 'up')"
          >
            ▲
          </button>
          <button
            type="button"
            class="arrow-btn"
            :disabled="idx === localRules.length - 1"
            aria-label="Move down (match later)"
            @click="bumpOrder(rule, 'down')"
          >
            ▼
          </button>
        </div>
        <div v-if="editingId === rule.id" class="rule-edit">
          <input
            v-model="editKeyword"
            class="input"
            maxlength="100"
            @keydown.enter.prevent="saveEdit(rule)"
            @keydown.escape="cancelEdit"
          />
          <div class="edit-minutes">
            <label class="minutes-field">
              There
              <input
                v-model.number="editThere"
                type="number"
                min="0"
                :max="MAX_TRAVEL_MINUTES"
                class="input minutes-input"
              />
            </label>
            <label class="minutes-field">
              Back
              <input
                v-model.number="editBack"
                type="number"
                min="0"
                :max="MAX_TRAVEL_MINUTES"
                class="input minutes-input"
              />
            </label>
            <select v-model="editCategory" class="input" aria-label="Category">
              <option value="">other (default)</option>
              <option value="work">work</option>
              <option value="personal">personal</option>
              <option value="health">health</option>
              <option value="other">other</option>
            </select>
          </div>
          <div class="edit-actions">
            <button type="button" class="primary-btn" @click="saveEdit(rule)">
              Save
            </button>
            <button type="button" class="ghost-btn" @click="cancelEdit">
              Cancel
            </button>
          </div>
        </div>
        <button
          v-else
          type="button"
          class="rule-summary"
          @click="startEdit(rule)"
        >
          <span class="rule-keyword">{{ rule.keyword }}</span>
          <span class="rule-details">
            −{{ rule.travel_there_minutes }}m / +{{ rule.travel_back_minutes }}m
            · {{ categoryLabel(rule.category) }}
          </span>
        </button>
        <button
          type="button"
          class="row-delete-btn"
          aria-label="Delete travel rule"
          @click="confirmDelete(rule)"
        >
          ×
        </button>
        <p v-if="rowError && rowError.id === rule.id" class="row-error">
          {{ rowError.message }}
        </p>
      </li>
    </ul>
    <p v-else class="empty-text">No travel rules yet — add one above.</p>
  </section>
</template>

<style scoped>
.travel-rules-list {
  background: var(--bg-panel);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hint-text {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.add-form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: flex-end;
}

.keyword-input {
  flex: 1;
  min-width: 160px;
}

.minutes-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--text-muted);
}

.minutes-input {
  width: 72px;
}

.input {
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 14px;
}

.primary-btn {
  background: var(--accent);
  color: var(--accent-contrast);
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
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

.ghost-btn {
  background: var(--bg-panel);
  color: var(--text-muted);
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 8px 16px;
  cursor: pointer;
}

.error-text {
  color: var(--danger-text);
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
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  border-radius: 6px;
}

.rule-row:hover {
  background: var(--bg-schedule-gap);
}

.order-controls {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.arrow-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 1px 4px;
}

.arrow-btn:hover:not(:disabled) {
  color: var(--text-primary);
}

.arrow-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.rule-summary {
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  font-size: 14px;
  color: var(--text-primary);
  padding: 4px 8px;
  border-radius: 6px;
  cursor: text;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rule-summary:hover {
  border-color: var(--border-strong);
  background: var(--bg-panel);
}

.rule-keyword {
  font-weight: 500;
}

.rule-details {
  font-size: 12px;
  color: var(--text-muted);
}

.row-delete-btn {
  background: transparent;
  border: none;
  color: var(--danger-text);
  font-size: 18px;
  cursor: pointer;
  width: 24px;
  height: 24px;
  border-radius: 6px;
}

.row-delete-btn:hover {
  background: var(--danger-surface);
}

.rule-edit {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.edit-minutes {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  flex-wrap: wrap;
}

.edit-actions {
  display: flex;
  gap: 6px;
}

.row-error {
  grid-column: 1 / -1;
  margin: 0;
  font-size: 12px;
  color: var(--danger-text);
}

.empty-text {
  margin: 0;
  color: var(--text-faint);
  font-style: italic;
  font-size: 13px;
}
</style>
