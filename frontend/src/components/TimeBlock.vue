<script setup lang="ts">
import { ref, computed, nextTick, inject, watch } from "vue"
import type { Ref } from "vue"
import type { TimeBlock, UndoAction, UserCategory } from "../types"
import { useSchedule } from "../composables/useSchedule"
import { useBlockCompletion } from "../composables/useBlockCompletion"
import { getCategoryColor } from "../utils/categoryColors"
import { useActiveTheme } from "../composables/useActiveTheme"
import {
  formatDurationMinutes,
  formatRemainingMinutes,
  timeToMinutes,
} from "../utils/scheduleTime"

const props = withDefaults(
  defineProps<{
    block: TimeBlock
    date: string
    isCurrent?: boolean
    remainingMinutes?: number | null
    categories?: UserCategory[]
  }>(),
  {
    isCurrent: false,
    remainingMinutes: null,
  },
)

const { updateBlock, deleteBlock } = useSchedule(props.date)
// Tracks the active theme reactively so the left-border color updates
// when the user switches themes while this block is mounted (without
// it, `getCategoryColor()` reads dataset.theme at call time only, with
// no Vue-tracked dep).
const activeTheme = useActiveTheme()

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

const scheduleDisabled = inject<Ref<boolean> | null>("scheduleDisabled", null)

function isDisabled(): boolean {
  return Boolean(scheduleDisabled?.value)
}

function onDragStart(event: PointerEvent) {
  if (isDisabled()) return
  if (drag && scheduleContainer?.value) {
    drag.startDrag(event, props.block, scheduleContainer.value)
  }
}

const editing = ref(false)
const editTitle = ref("")
const errorMessage = ref("")
const titleInput = ref<HTMLInputElement | null>(null)

// Local override for the checkbox: native <input type="checkbox"> flips on
// click before Vue re-applies :checked, so binding the prop alone desyncs on
// failure. displayedCompleted is the single source of truth for the UI.
const displayedCompleted = ref(props.block.is_completed)
// Completion network/retry/undo/abort logic is owned by the shared controller
// so the timeline checkbox and the PiP focus indicator cannot diverge. This
// instance is private to this row (per-call-site factory, not a singleton).
const completion = useBlockCompletion({ updateBlock, undo, isDisabled })
const { saving } = completion
const disabled = computed(() => isDisabled())
// External updates to this block's completion (an AI mutation, a concurrent
// tab, this chain's own success reload) re-align the checkbox — but only while
// no local toggle is in flight. During a local chain `saving` is true and the
// optimistic value must win, or an *older* chain's late reload would clobber a
// *newer* click for the duration of the retry window.
watch(
  () => props.block.is_completed,
  (v) => {
    if (!saving.value) displayedCompleted.value = v
  },
)
// Schedule.vue keys rows by index, so this instance can be reused for a
// different block mid-flight. When the block identity changes, abort the
// in-flight chain (its generation guard then bails without touching state) and
// re-align all local UI state to the new block — otherwise the old chain's
// optimistic checked / saving spinner / error would stick on the wrong row.
watch(
  () => props.block.id,
  () => {
    // reset() aborts the in-flight chain AND clears the controller's
    // saving/errorState; re-align this row's local UI to the new block.
    completion.reset()
    displayedCompleted.value = props.block.is_completed
    errorMessage.value = ""
  },
)

const durationMinutes = computed(() => {
  return timeToMinutes(props.block.end_time) - timeToMinutes(props.block.start_time)
})

const duration = computed(() => formatDurationMinutes(durationMinutes.value))

const isCompact = computed(() => durationMinutes.value <= 30)
const remainingLabel = computed(() => {
  if (!props.isCurrent || props.remainingMinutes === null || props.remainingMinutes <= 0) {
    return null
  }
  return formatRemainingMinutes(props.remainingMinutes)
})

async function startEditing() {
  if (isDisabled()) return
  editTitle.value = props.block.title
  editing.value = true
  await nextTick()
  titleInput.value?.focus()
}

async function saveTitle() {
  // Guard: ``@keydown.enter`` and ``@blur`` both bind to ``saveTitle``.
  // After Enter, Vue removes the input from the DOM (when ``editing``
  // flips false), which fires blur, which re-enters this handler.
  // Setting ``editing.value = false`` BEFORE the network await ensures
  // the second call short-circuits here. (A flag reset in a ``finally``
  // wouldn't work — by the time blur fires sequentially the flag is
  // already cleared. The ``editing`` ref is the right state to gate on.)
  if (!editing.value) return

  const trimmed = editTitle.value.trim()
  if (!trimmed || trimmed === props.block.title) {
    editing.value = false
    return
  }

  // Take edit mode down NOW. Vue will remove the input on next tick;
  // the resulting blur will re-enter ``saveTitle`` and immediately
  // hit the ``!editing.value`` early-return above.
  editing.value = false

  const snapshot = undo?.snapshotBlocks()
  // Bind undo to the date active when the mutation starts (see issue #21).
  const scheduleDate = props.date
  const result = await updateBlock(props.block.id, { title: trimmed })
  if (result.ok) {
    if (undo && snapshot) {
      undo.pushUndo({
        description: `Renamed "${props.block.title}" to "${trimmed}"`,
        type: "edit",
        previousBlocks: snapshot,
        scheduleDate,
        silent: true,
      })
    }
  } else {
    // Re-open the input so the user can retry; clearing it would
    // discard their typed value.
    errorMessage.value = "Failed to update title"
    editing.value = true
  }
}

function cancelEditing() {
  editing.value = false
}

async function toggleCompleted() {
  if (isDisabled()) return
  const desired = !displayedCompleted.value
  // Optimistic flip (local single-source-of-truth for the checkbox) — the
  // controller owns the network/retry/undo/abort chain.
  displayedCompleted.value = desired
  errorMessage.value = ""
  const outcome = await completion.setCompleted(props.block, props.date, desired)
  if (outcome === "failure") {
    // Retries exhausted while this chain is still newest: revert the optimistic
    // flip to the LIVE reloaded prop (not a value captured at start) and surface
    // the copy the timeline test pins.
    displayedCompleted.value = props.block.is_completed
    errorMessage.value = "Failed to update"
  } else if (outcome === "success") {
    errorMessage.value = ""
  }
  // "superseded": a newer chain (or reset/dispose) owns reconciliation — touch
  // nothing.
}

async function handleDelete() {
  if (isDisabled()) return
  if (!window.confirm("Delete this block?")) return
  errorMessage.value = ""
  const snapshot = undo?.snapshotBlocks()
  const scheduleDate = props.date
  const result = await deleteBlock(props.block.id)
  if (result.ok) {
    if (undo && snapshot) {
      undo.pushUndo({
        description: `Deleted "${props.block.title}"`,
        type: "delete",
        previousBlocks: snapshot,
        scheduleDate,
        silent: true,
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
      completed: displayedCompleted,
      compact: isCompact,
      dragging: drag?.isDragging.value && drag?.dragBlockId.value === block.id,
      shifting: drag?.shiftedBlockIds.value.has(block.id),
    }"
    :style="{ borderLeftColor: getCategoryColor(block.category, activeTheme, props.categories) }"
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
          :checked="displayedCompleted"
          class="checkbox"
          :class="{ saving }"
          :disabled="disabled"
          @change="toggleCompleted"
        />
        <span class="time-badge">{{ block.start_time }}–{{ block.end_time }}</span>
        <span v-if="remainingLabel" class="remaining-badge">{{ remainingLabel }}</span>
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
          :class="{ 'title-completed': displayedCompleted }"
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
        <span v-if="remainingLabel" class="remaining-badge">{{ remainingLabel }}</span>
        <button class="delete-btn" @click="handleDelete">&times;</button>
      </div>
      <div class="block-body">
        <input
          type="checkbox"
          :checked="displayedCompleted"
          class="checkbox"
          :class="{ saving }"
          :disabled="disabled"
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
          :class="{ 'title-completed': displayedCompleted }"
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
  color: var(--danger-text);
}

.time-block {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: var(--bg-panel);
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
  color: var(--text-muted);
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
  color: var(--text-muted);
  font-weight: 500;
}

.duration {
  font-size: 12px;
  color: var(--text-faint);
}

.remaining-badge {
  flex-shrink: 0;
  font-size: 12px;
  line-height: 1;
  color: var(--accent);
  font-weight: 600;
  white-space: nowrap;
}

.delete-btn {
  margin-left: auto;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
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

.checkbox.saving {
  opacity: 0.5;
  cursor: progress;
}

.title {
  cursor: pointer;
  font-size: 15px;
}

.title:hover {
  color: var(--accent);
}

.title-completed {
  text-decoration: line-through;
  color: var(--text-faint);
}

.title-input {
  flex: 1;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 15px;
}
</style>
