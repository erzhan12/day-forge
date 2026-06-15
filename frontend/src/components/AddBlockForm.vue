<script setup lang="ts">
import type { Ref } from "vue"
import { computed, ref, watch, inject } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useSchedule } from "../composables/useSchedule"

const props = defineProps<{
  date: string
  initialStartTime?: string
  initialEndTime?: string
}>()

const { createBlock } = useSchedule(() => props.date)

const undo = inject<{
  pushUndo: (action: UndoAction) => void
  snapshotBlocks: () => TimeBlock[]
}>("undo")

const scheduleDisabled = inject<Ref<boolean> | null>("scheduleDisabled", null)
const isDisabled = computed(() => Boolean(scheduleDisabled?.value))

const title = ref("")
const startTime = ref(props.initialStartTime ?? "09:00")
const endTime = ref(props.initialEndTime ?? "10:00")
const category = ref<"work" | "personal" | "health" | "other">("work")
const showForm = ref(false)
const submitting = ref(false)
const errorMessage = ref("")

watch(
  () => [props.initialStartTime, props.initialEndTime],
  ([s, e]) => {
    if (s) startTime.value = s
    if (e) endTime.value = e
    if (s || e) showForm.value = true
  },
)

async function handleSubmit() {
  if (isDisabled.value) return
  if (!title.value.trim()) return
  submitting.value = true
  errorMessage.value = ""
  const snapshot = undo?.snapshotBlocks()
  const blockTitle = title.value.trim()
  // Bind undo to the date active when the mutation starts, not when the
  // response resolves — if the user navigates dates while the request is
  // in flight, ``props.date`` would shift and undo would restore this
  // day's snapshot onto a different date. Issue #21.
  const scheduleDate = props.date
  const result = await createBlock({
    title: blockTitle,
    start_time: startTime.value,
    end_time: endTime.value,
    category: category.value,
  })
  submitting.value = false
  if (result.ok) {
    if (undo && snapshot) {
      undo.pushUndo({
        description: `Added "${blockTitle}"`,
        type: "add",
        previousBlocks: snapshot,
        scheduleDate,
        silent: true,
      })
    }
    title.value = ""
    showForm.value = false
  } else {
    const errs = result.errors ?? {}
    errorMessage.value = Object.values(errs).flat().join(", ") || "Failed to create block"
  }
}

function cancel() {
  title.value = ""
  showForm.value = false
}
</script>

<template>
  <div class="add-block">
    <button
      v-if="!showForm"
      class="add-btn"
      :disabled="isDisabled"
      @click="showForm = true"
    >
      + Add Block
    </button>
    <form v-else class="add-form" @submit.prevent="handleSubmit">
      <div v-if="errorMessage" class="error-banner">{{ errorMessage }}</div>
      <input
        v-model="title"
        type="text"
        placeholder="Block title"
        class="input title-input"
        required
      />
      <div class="time-row">
        <label>
          Start
          <input v-model="startTime" type="time" step="300" class="input" />
        </label>
        <label>
          End
          <input v-model="endTime" type="time" step="300" class="input" />
        </label>
        <label>
          Category
          <select v-model="category" class="input">
            <option value="work">Work</option>
            <option value="personal">Personal</option>
            <option value="health">Health</option>
            <option value="other">Other</option>
          </select>
        </label>
      </div>
      <div class="form-actions">
        <button type="submit" class="submit-btn" :disabled="submitting">
          {{ submitting ? "Adding..." : "Add" }}
        </button>
        <button type="button" class="cancel-btn" @click="cancel">Cancel</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.add-block {
  padding: 16px;
}

.add-btn {
  width: 100%;
  padding: 12px;
  border: 2px dashed #d1d5db;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 15px;
  font-weight: 500;
}

.add-btn:hover {
  border-color: var(--text-faint);
  color: var(--text-secondary);
  background: var(--bg-schedule-gap);
}

.error-banner {
  background: var(--danger-surface);
  color: var(--danger-text);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
}

.add-form {
  background: var(--bg-panel);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.input {
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 14px;
}

.title-input {
  width: 100%;
}

.time-row {
  display: flex;
  gap: 12px;
}

.time-row label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

.form-actions {
  display: flex;
  gap: 8px;
}

.submit-btn {
  padding: 8px 20px;
  background: var(--accent);
  color: var(--accent-contrast);
  border: none;
  border-radius: 6px;
  font-weight: 500;
}

.submit-btn:hover {
  background: var(--accent-hover);
}

.cancel-btn {
  padding: 8px 20px;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  color: var(--text-muted);
}

.cancel-btn:hover {
  background: var(--bg-schedule-gap);
}
</style>
