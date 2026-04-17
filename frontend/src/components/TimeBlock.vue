<script setup lang="ts">
import { ref, computed, nextTick, inject } from "vue"
import type { Ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useSchedule } from "../composables/useSchedule"

const props = defineProps<{
  block: TimeBlock
  date: string
}>()

const { updateBlock, deleteBlock } = useSchedule(props.date)

const undo = inject<{
  pushUndo: (action: UndoAction) => void
  snapshotBlocks: () => TimeBlock[]
}>("undo")

const drag = inject<{
  startDrag: (event: PointerEvent, block: TimeBlock, container: HTMLElement) => void
  isDragging: Ref<boolean>
  dragBlockId: Ref<number | null>
  shiftedBlockIds: Ref<Set<number>>
}>("drag")

const scheduleContainer = inject<Ref<HTMLElement | null>>("scheduleContainer")

function onDragStart(event: PointerEvent) {
  if (drag && scheduleContainer?.value) {
    drag.startDrag(event, props.block, scheduleContainer.value)
  }
}

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

const durationMinutes = computed(() => {
  const [sh, sm] = props.block.start_time.split(":").map(Number)
  const [eh, em] = props.block.end_time.split(":").map(Number)
  return eh * 60 + em - (sh * 60 + sm)
})

const duration = computed(() => {
  const mins = durationMinutes.value
  if (mins >= 60) {
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  return `${mins}m`
})

const isCompact = computed(() => durationMinutes.value <= 30)

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
  const snapshot = undo?.snapshotBlocks()
  const result = await updateBlock(props.block.id, { title: trimmed })
  if (result.ok) {
    editing.value = false
    if (undo && snapshot) {
      undo.pushUndo({
        description: `Renamed "${props.block.title}" to "${trimmed}"`,
        type: "edit",
        previousBlocks: snapshot,
        scheduleDate: props.date,
      })
    }
  } else {
    errorMessage.value = "Failed to update title"
  }
}

function cancelEditing() {
  editing.value = false
}

async function toggleCompleted() {
  errorMessage.value = ""
  const snapshot = undo?.snapshotBlocks()
  const result = await updateBlock(props.block.id, {
    is_completed: !props.block.is_completed,
  })
  if (result.ok) {
    if (undo && snapshot) {
      const action = props.block.is_completed ? "Unchecked" : "Checked"
      undo.pushUndo({
        description: `${action} "${props.block.title}"`,
        type: "toggle",
        previousBlocks: snapshot,
        scheduleDate: props.date,
      })
    }
  } else {
    errorMessage.value = "Failed to update"
  }
}

async function handleDelete() {
  if (!window.confirm("Delete this block?")) return
  errorMessage.value = ""
  const snapshot = undo?.snapshotBlocks()
  const result = await deleteBlock(props.block.id)
  if (result.ok) {
    if (undo && snapshot) {
      undo.pushUndo({
        description: `Deleted "${props.block.title}"`,
        type: "delete",
        previousBlocks: snapshot,
        scheduleDate: props.date,
      })
    }
  } else {
    errorMessage.value = "Failed to delete"
  }
}
</script>

<template>
  <div
    class="time-block"
    :class="{
      completed: block.is_completed,
      compact: isCompact,
      dragging: drag?.isDragging.value && drag?.dragBlockId.value === block.id,
      shifting: drag?.shiftedBlockIds.value.has(block.id),
    }"
    :style="{ borderLeftColor: categoryColors[block.category] }"
  >
    <div
      class="drag-handle"
      @pointerdown.stop="onDragStart"
    >
      <span class="grip-icon">&#x2807;</span>
    </div>
    <template v-if="isCompact">
      <div class="compact-row">
        <input
          type="checkbox"
          :checked="block.is_completed"
          class="checkbox"
          @change="toggleCompleted"
        />
        <span class="time-badge">{{ block.start_time }}–{{ block.end_time }}</span>
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
        <button class="delete-btn" @click="handleDelete">&times;</button>
      </div>
    </template>
    <template v-else>
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
    </template>
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
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: white;
  border-left: 4px solid #6b7280;
  border-radius: 8px;
  padding: 12px 16px 12px 32px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  box-sizing: border-box;
  height: 100%;
  overflow: hidden;
}

.time-block.completed {
  opacity: 0.6;
}

.time-block.compact {
  padding: 4px 8px 4px 28px;
}

.compact-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 13px;
}

.compact-row .time-badge {
  flex-shrink: 0;
}

.compact-row .title,
.compact-row .title-input {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.compact-row .checkbox {
  width: 14px;
  height: 14px;
}

.compact-row .delete-btn {
  margin-left: 0;
  width: 20px;
  height: 20px;
  font-size: 14px;
}

.time-block.dragging {
  opacity: 0.3;
  pointer-events: none;
}

.time-block.shifting {
  transition: transform 200ms ease;
}

.drag-handle {
  position: absolute;
  left: 4px;
  top: 0;
  bottom: 0;
  width: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  color: #d1d5db;
  font-size: 16px;
  touch-action: none;
  user-select: none;
}

.drag-handle:hover {
  color: #6b7280;
}

.drag-handle:active {
  cursor: grabbing;
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
