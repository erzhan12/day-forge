<script setup lang="ts">
import { ref, computed, nextTick } from "vue"
import type { TimeBlock } from "../types"
import { useSchedule } from "../composables/useSchedule"

const props = defineProps<{
  block: TimeBlock
  date: string
}>()

const { updateBlock, deleteBlock } = useSchedule(props.date)

const editing = ref(false)
const editTitle = ref("")
const errorMessage = ref("")
const titleInput = ref<HTMLInputElement | null>(null)

const categoryColors: Record<string, string> = {
  work: "#3B82F6",
  personal: "#8B5CF6",
  health: "#10B981",
  other: "#6B7280",
}

const duration = computed(() => {
  const [sh, sm] = props.block.start_time.split(":").map(Number)
  const [eh, em] = props.block.end_time.split(":").map(Number)
  const mins = eh * 60 + em - (sh * 60 + sm)
  if (mins >= 60) {
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  return `${mins}m`
})

async function startEditing() {
  editTitle.value = props.block.title
  editing.value = true
  await nextTick()
  titleInput.value?.focus()
}

async function saveTitle() {
  const trimmed = editTitle.value.trim()
  if (!trimmed || trimmed === props.block.title) {
    editing.value = false
    return
  }
  const result = await updateBlock(props.block.id, { title: trimmed })
  if (result.ok) {
    editing.value = false
  }
}

function cancelEditing() {
  editing.value = false
}

async function toggleCompleted() {
  errorMessage.value = ""
  const result = await updateBlock(props.block.id, {
    is_completed: !props.block.is_completed,
  })
  if (!result.ok) {
    errorMessage.value = "Failed to update"
  }
}

async function handleDelete() {
  if (!window.confirm("Delete this block?")) return
  errorMessage.value = ""
  const result = await deleteBlock(props.block.id)
  if (!result.ok) {
    errorMessage.value = "Failed to delete"
  }
}
</script>

<template>
  <div
    class="time-block"
    :class="{ completed: block.is_completed }"
    :style="{ borderLeftColor: categoryColors[block.category] }"
  >
    <div class="block-header">
      <span class="time-badge">{{ block.start_time }} – {{ block.end_time }}</span>
      <span class="duration">{{ duration }}</span>
      <button class="delete-btn" @click="handleDelete">&times;</button>
    </div>
    <div class="block-body">
      <input
        type="checkbox"
        :checked="block.is_completed"
        class="checkbox"
        @change="toggleCompleted"
      />
      <input
        v-if="editing"
        ref="titleInput"
        v-model="editTitle"
        class="title-input"
        @blur="saveTitle"
        @keydown.enter="saveTitle"
        @keydown.escape="cancelEditing"
      />
      <span
        v-else
        class="title"
        :class="{ 'title-completed': block.is_completed }"
        @click="startEditing"
      >
        {{ block.title }}
      </span>
    </div>
    <div v-if="errorMessage" class="block-error">{{ errorMessage }}</div>
  </div>
</template>

<style scoped>
.block-error {
  margin-top: 4px;
  font-size: 12px;
  color: #dc2626;
}

.time-block {
  background: white;
  border-left: 4px solid #6b7280;
  border-radius: 8px;
  padding: 12px 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  box-sizing: border-box;
  height: 100%;
  overflow: hidden;
}

.time-block.completed {
  opacity: 0.6;
}

.block-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.time-badge {
  font-size: 12px;
  color: #6b7280;
  font-weight: 500;
}

.duration {
  font-size: 12px;
  color: #9ca3af;
}

.delete-btn {
  margin-left: auto;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #9ca3af;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.delete-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}

.block-body {
  display: flex;
  align-items: center;
  gap: 8px;
}

.checkbox {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  cursor: pointer;
}

.title {
  cursor: pointer;
  font-size: 15px;
}

.title:hover {
  color: #3b82f6;
}

.title-completed {
  text-decoration: line-through;
  color: #9ca3af;
}

.title-input {
  flex: 1;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 15px;
}
</style>
