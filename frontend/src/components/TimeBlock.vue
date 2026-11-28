<script setup lang="ts">
import { ref, computed, nextTick, inject, onBeforeUnmount, useId, watch } from "vue"
import type { TimeBlock, UserCategory } from "../types"
import { ScheduleContainerKey, ScheduleDisabledKey, ScheduleDragKey, ScheduleUndoKey } from "../composables/scheduleContext"
import { useSchedule } from "../composables/useSchedule"
import { registerMutationUndo } from "../composables/useMutationUndo"
import { useBlockCompletion } from "../composables/useBlockCompletion"
import { getCategoryColor, tickVariantFor } from "../utils/categoryColors"
import { useActiveTheme } from "../composables/useActiveTheme"
import DeleteConfirmationDialog from "./DeleteConfirmationDialog.vue"
import BlockTooltip from "./BlockTooltip.vue"
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
    /** "compact" is the one-line Dark 4a row for short blocks (0106). */
    density?: "full" | "compact"
    /** Opt-in hover/focus/long-press tooltip (Dark 4a only, 0106). */
    tooltip?: boolean
    /** Show a cascaded block's new start while a drag is in progress. */
    shiftPreview?: boolean
    /** Dark 4a phone row (feature 0113): × deletes at once, the handle is inert,
     *  no end time or countdown, errors float below the 52 px row. */
    mobile?: boolean
  }>(),
  {
    isCurrent: false,
    remainingMinutes: null,
    density: "full",
    tooltip: false,
    shiftPreview: false,
    mobile: false,
  },
)
const compact = computed(() => props.density === "compact")
// A fixed-height row cannot grow an error line, so it floats like compact.
const floatingError = computed(() => compact.value || props.mobile)

const { updateBlock, deleteBlock } = useSchedule(() => props.date)
// Tracks the active theme reactively so the left-border color updates
// when the user switches themes while this block is mounted (without
// it, `getCategoryColor()` reads dataset.theme at call time only, with
// no Vue-tracked dep).
const activeTheme = useActiveTheme()
const categoryColor = computed(() => getCategoryColor(props.block.category, activeTheme.value, props.categories))
// Shared .df-checkbox (feature 0105): fill with the category colour and pick
// the tick that contrasts with it.
const checkboxStyle = computed(() => ({
  "--checkbox-color": categoryColor.value,
  "--checkbox-tick": `var(--checkbox-tick-${tickVariantFor(categoryColor.value)})`,
}))

const undo = inject(ScheduleUndoKey, undefined)

const drag = inject(ScheduleDragKey, undefined)

const scheduleContainer = inject(ScheduleContainerKey, undefined)

const scheduleDisabled = inject(ScheduleDisabledKey, null)

function isDisabled(): boolean {
  return Boolean(scheduleDisabled?.value)
}

function onDragStart(event: PointerEvent) {
  if (props.mobile || isDisabled()) return
  if (drag && scheduleContainer?.value) {
    drag.startDrag(event, props.block, scheduleContainer.value)
  }
}

const editing = ref(false)
const editTitle = ref("")
const errorMessage = ref("")
const titleInput = ref<HTMLInputElement | null>(null)
const confirmingDelete = ref(false)

// Local override for the checkbox: native <input type="checkbox"> flips on
// click before Vue re-applies :checked, so binding the prop alone desyncs on
// failure. displayedCompleted is the single source of truth for the UI.
const displayedCompleted = ref(props.block.is_completed)
// The shared schedule controller owns writes and reconciliation.
const completion = useBlockCompletion({ updateBlock, undo, isDisabled })
const { saving } = completion
const disabled = computed(() => isDisabled())
// A confirmation belongs to the block and day shown when it was opened.
// Dismiss it if navigation, reconciliation, or another write changes context.
watch([() => props.date, () => props.block, disabled], () => {
  confirmingDelete.value = false
})
// External updates to this block's completion (an AI mutation, a concurrent
// tab, this chain's own success reload) re-align the checkbox — but only while
// no local toggle is in flight. During a local chain `saving` is true and the
// optimistic value must win, or an *older* chain's late reload would clobber a
// *newer* click while queued writes settle.
watch(
  () => props.block.is_completed,
  (v) => {
    if (!saving.value) displayedCompleted.value = v
  },
)
// A changed identity resets the row UI without canceling an accepted write.
watch(
  [() => props.date, () => props.block.id],
  () => {
    completion.reset()
    editing.value = false
    displayedCompleted.value = props.block.is_completed
    errorMessage.value = ""
  },
)

const durationMinutes = computed(() => {
  return timeToMinutes(props.block.end_time) - timeToMinutes(props.block.start_time)
})

const duration = computed(() => formatDurationMinutes(durationMinutes.value))

const remainingLabel = computed(() => {
  if (compact.value || props.mobile) return null
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
  if (!editing.value || isDisabled()) return

  const trimmed = editTitle.value.trim()
  if (!trimmed || trimmed === props.block.title) {
    editing.value = false
    return
  }

  // Take edit mode down NOW. Vue will remove the input on next tick;
  // the resulting blur will re-enter ``saveTitle`` and immediately
  // hit the ``!editing.value`` early-return above.
  editing.value = false

  const originalId = props.block.id
  const originalDate = props.date
  const originalTitle = props.block.title
  const result = await updateBlock(originalId, { title: trimmed })
  if (result.ok) {
    registerMutationUndo(result, undo?.pushUndo, {
      description: `Renamed "${originalTitle}" to "${trimmed}"`,
      type: "edit",
      silent: true,
    })
  } else if (props.block.id === originalId && props.date === originalDate) {
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
  if (isDisabled() && !saving.value) return
  const desired = !displayedCompleted.value
  // Keep the latest intent visible while completion writes are serialized.
  displayedCompleted.value = desired
  errorMessage.value = ""
  const outcome = await completion.setCompleted(props.block, props.date, desired)
  if (outcome === "failure") {
    // Failure reconciles against the current canonical block.
    displayedCompleted.value = props.block.is_completed
    errorMessage.value = "Failed to update"
  } else if (outcome === "success") {
    errorMessage.value = ""
  } else if (!saving.value) {
    // A conflict can cancel an unsent rapid toggle after reconciliation.
    displayedCompleted.value = props.block.is_completed
  }
}

// ----- Tooltip and long press (opt-in, feature 0106) -----------------------
const rootRef = ref<HTMLElement | null>(null)
const titleRef = ref<HTMLElement | null>(null)
const tooltipId = `block-tip-${useId()}`
const errorId = `block-err-${useId()}`
const tooltipOpen = ref(false)
const LONG_PRESS_MS = 500
const LONG_PRESS_SLOP_PX = 8
let longPressTimer: ReturnType<typeof setTimeout> | null = null
let longPressOrigin: { x: number; y: number } | null = null
let suppressNextClick = false

const categoryLabel = computed(() =>
  props.categories?.find((item) => item.slug === props.block.category)?.label ?? props.block.category)
const tooltipRange = computed(() =>
  `${props.block.start_time}–${props.block.end_time} · ${duration.value}`)

function titleTruncated(): boolean {
  const el = titleRef.value
  return Boolean(el && el.scrollWidth > el.clientWidth)
}

function showTooltip() {
  if (!props.tooltip || editing.value) return
  if (compact.value || titleTruncated()) tooltipOpen.value = true
}

function hideTooltip() {
  tooltipOpen.value = false
}

function onFocusOut(event: FocusEvent) {
  const next = event.relatedTarget as Node | null
  if (!next || !rootRef.value?.contains(next)) hideTooltip()
}

function clearLongPress() {
  if (longPressTimer !== null) clearTimeout(longPressTimer)
  longPressTimer = null
  longPressOrigin = null
}

function onPointerDown(event: PointerEvent) {
  if (!props.tooltip || event.pointerType !== "touch" || editing.value) return
  clearLongPress()
  longPressOrigin = { x: event.clientX, y: event.clientY }
  longPressTimer = setTimeout(() => {
    longPressTimer = null
    longPressOrigin = null
    suppressNextClick = true
    showTooltip()
  }, LONG_PRESS_MS)
}

function onPointerMove(event: PointerEvent) {
  if (!longPressOrigin) return
  const dx = event.clientX - longPressOrigin.x
  const dy = event.clientY - longPressOrigin.y
  if (Math.hypot(dx, dy) > LONG_PRESS_SLOP_PX) clearLongPress()
}

// Only a completed long press swallows the click that follows it, so an
// ordinary tap still opens the title editor.
function onClickCapture(event: MouseEvent) {
  if (!suppressNextClick) return
  suppressNextClick = false
  event.preventDefault()
  event.stopPropagation()
}

watch(editing, (value) => {
  if (value) {
    clearLongPress()
    hideTooltip()
  }
})
watch(() => props.block, () => {
  clearLongPress()
  suppressNextClick = false
  hideTooltip()
})
onBeforeUnmount(clearLongPress)

const shiftTarget = computed(() => {
  if (!props.shiftPreview || !drag?.shiftedBlockIds.value.has(props.block.id)) return null
  return drag.previewBlocks?.value.find((item) => item.id === props.block.id)?.start_time ?? null
})

// Mobile deletes on the tap (feature 0113); the Undo entry is the safety net.
function onDeleteClick() {
  confirmingDelete.value = true
  if (props.mobile) void handleDelete()
}

async function handleDelete() {
  if (isDisabled() || !confirmingDelete.value) return
  confirmingDelete.value = false
  errorMessage.value = ""
  const blockId = props.block.id
  const scheduleDate = props.date
  const blockTitle = props.block.title
  const result = await deleteBlock(blockId)
  if (result.ok) {
    registerMutationUndo(result, undo?.pushUndo, {
      description: `Deleted "${blockTitle}"`,
      type: "delete",
      silent: true,
    })
  } else if (props.block.id === blockId && props.date === scheduleDate) {
    errorMessage.value = "Failed to delete"
  }
}
</script>

<template>
  <div
    ref="rootRef"
    class="time-block"
    :class="{
      completed: displayedCompleted,
      dragging: drag?.isDragging.value && drag?.dragBlockId.value === block.id,
      shifting: drag?.shiftedBlockIds.value.has(block.id),
      'density-compact': compact,
      'density-mobile': mobile,
    }"
    :style="{ borderLeftColor: categoryColor }"
    :aria-describedby="tooltipOpen ? tooltipId : (floatingError && errorMessage ? errorId : undefined)"
    @mouseenter="showTooltip"
    @mouseleave="hideTooltip"
    @focusin="showTooltip"
    @focusout="onFocusOut"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="clearLongPress"
    @pointercancel="clearLongPress"
    @click.capture="onClickCapture"
  >
    <div
      class="drag-handle"
      :aria-hidden="mobile ? 'true' : undefined"
      @pointerdown.stop="onDragStart"
    >
      <span class="grip-icon">&#x2807;</span>
    </div>
    <!-- One row for every duration so short and long cards line up. -->
    <div class="block-row">
      <label class="check-hit">
        <input
          type="checkbox"
          :checked="displayedCompleted"
          class="checkbox df-checkbox"
          :class="{ saving }"
          :style="checkboxStyle"
          :disabled="disabled"
          :aria-label="`Complete ${block.title}`"
          @change="toggleCompleted"
        />
      </label>
      <span class="time-badge"><span class="time-start">{{ block.start_time }}</span><span v-if="!compact && !mobile" class="time-end">–{{ block.end_time }}</span></span>
      <span class="duration">{{ duration }}</span>
      <span v-if="shiftTarget" class="shift-badge" data-testid="shift-badge">→ {{ shiftTarget }}</span>
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
        ref="titleRef"
        class="title"
        :class="{ 'title-completed': displayedCompleted }"
        @click="startEditing"
      >
        {{ block.title }}
      </span>
      <button
        class="delete-btn"
        :aria-label="`Delete ${block.title}`"
        :disabled="disabled"
        @click="onDeleteClick"
      >&times;</button>
    </div>
    <div v-if="errorMessage && !floatingError" class="block-error">{{ errorMessage }}</div>
    <!-- A one-line compact card would clip the error, so it floats below. -->
    <BlockTooltip v-if="errorMessage && floatingError" :id="errorId" :anchor="rootRef" role="alert">
      {{ errorMessage }}
    </BlockTooltip>
    <BlockTooltip v-if="tooltipOpen" :id="tooltipId" :anchor="rootRef">
      <strong class="tip-title">{{ block.title }}</strong>
      <span class="tip-line">{{ tooltipRange }}</span>
      <span class="tip-line">{{ categoryLabel }}</span>
    </BlockTooltip>
    <DeleteConfirmationDialog
      v-if="confirmingDelete"
      heading="Delete block?"
      :message="`Delete “${block.title}”? You can restore it with Undo.`"
      @cancel="confirmingDelete = false"
      @confirm="handleDelete"
    />
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
  padding: 4px 8px 4px 28px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
  box-sizing: border-box;
  height: 100%;
  overflow: hidden;
  /* Lets the narrow-card query below drop secondary details. */
  container-type: inline-size;
}

.time-block.completed {
  opacity: 0.6;
}

.block-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
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

.time-badge {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

.duration {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-faint);
}

.remaining-badge {
  /* Shrinks before the title does on narrow cards. */
  flex-shrink: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
  line-height: 1;
  color: var(--accent);
  font-weight: 600;
  white-space: nowrap;
}

.delete-btn {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.delete-btn:hover {
  background: #fee2e2;
  color: #ef4444;
}

/* Size, paint and states come from the global .df-checkbox (app.css). */
.checkbox.saving {
  opacity: 0.5;
  cursor: progress;
}

.title,
.title-input {
  flex: 1 0 0;
  /* Keeps the title readable and clickable however many badges the row has. */
  min-width: 48px;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.title {
  cursor: pointer;
}

.title:hover {
  color: var(--accent);
}

.title-completed {
  text-decoration: line-through;
  color: var(--text-faint);
}

.title-input {
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 2px 6px;
}

/* Full density: the checkbox label is layout-neutral. */
.check-hit {
  display: contents;
}

.shift-badge {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.tip-title,
.tip-line {
  display: block;
}

.tip-title {
  font-weight: 600;
}

/* Compact density (feature 0106, Dark 4a only): one centred line inside a
   28 px card. Hit areas come from real 24 px boxes, not padding. */
.time-block.density-compact {
  padding-top: 0;
  padding-bottom: 0;
}

.density-compact .block-row {
  line-height: 16px;
  gap: 6px;
}

.density-compact .check-hit {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  /* Starts right after the 24 px drag handle; never overlaps it. */
  margin-right: -4px;
  cursor: pointer;
}

.density-compact .time-badge,
.density-compact .duration {
  font-size: 13px;
  color: var(--text-secondary);
}

.density-compact .title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.density-compact .title-input {
  box-sizing: border-box;
  height: 20px;
  padding: 0 6px;
  font-size: 13px;
  line-height: 18px;
}

.density-compact .delete-btn {
  width: 24px;
  height: 24px;
  font-size: 16px;
  color: var(--text-secondary);
}

/* Phone-width cards: the time range already implies the duration, and on
   the current block the countdown matters more than the range. */
@container (max-width: 300px) {
  .duration,
  .block-row:has(.remaining-badge) .time-badge {
    display: none;
  }

  /* Compact rows keep start time, duration and × at every width. */
  .density-compact .duration,
  .density-compact .time-badge {
    display: inline;
  }
}
</style>
