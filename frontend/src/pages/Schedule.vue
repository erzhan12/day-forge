<script setup lang="ts">
import { computed, ref, provide, onMounted, onUnmounted, watch } from "vue"
import { Link, router } from "@inertiajs/vue3"
import type { TimeBlock as TimeBlockType, Schedule, RenderItem } from "../types"
import DateNavigator from "../components/DateNavigator.vue"
import TimeBlock from "../components/TimeBlock.vue"
import GapSlot from "../components/GapSlot.vue"
import AddBlockForm from "../components/AddBlockForm.vue"
import NowLine from "../components/NowLine.vue"
import UndoToast from "../components/UndoToast.vue"
import CommandBar from "../components/CommandBar.vue"
import ChatSidebar from "../components/ChatSidebar.vue"
import DraftBadge from "../components/DraftBadge.vue"
import RegenerateDraftButton from "../components/RegenerateDraftButton.vue"
import { todayString } from "../utils/date"
import { useViewport } from "../composables/useViewport"
import {
  readChatSidebarOpen,
  writeChatSidebarOpen,
} from "../utils/chatSidebarStorage"
import {
  DAY_START, DAY_END, DAY_START_MINUTES, DAY_END_MINUTES,
  PX_PER_MINUTE, timeToMinutes, minutesToTime,
} from "../utils/scheduleTime"
import { useSchedule } from "../composables/useSchedule"
import { useUndo } from "../composables/useUndo"
import { useDrag } from "../composables/useDrag"
import { useDraft } from "../composables/useDraft"
import { useChat } from "../composables/useChat"
import { useThemeFromProps } from "../composables/useThemeFromProps"
import "../app.css"

useThemeFromProps()

// Extend RenderItem with overlay variants for items containing the current time
interface DisplayItem {
  type: "block" | "gap" | "block-with-now" | "gap-with-now"
  block?: TimeBlockType
  start_time: string
  end_time: string
  duration_minutes: number
}

const props = withDefaults(
  defineProps<{
    schedule: Schedule
    blocks: TimeBlockType[]
    date: string
    auto_draft_pending?: boolean
    has_template_for_type?: boolean
    slot_type?: "weekday" | "weekend"
  }>(),
  {
    auto_draft_pending: false,
    has_template_for_type: false,
    slot_type: "weekday",
  },
)

const prefillStart = ref<string | undefined>()
const prefillEnd = ref<string | undefined>()
const scheduleBodyRef = ref<HTMLElement | null>(null)

// Initialize composables
const { reorderBlocks } = useSchedule(props.date)
const getBlocks = () => props.blocks
const {
  currentToast, pushUndo, performUndo, snapshotBlocks, dismissToast,
} = useUndo(props.date, getBlocks)

// Draft generation state — module-level singleton inside useDraft, single
// consumer is this page.
const { isGeneratingDraft, lastDraftError, generateDraft } = useDraft()

// Schedule-wide disabled flag: while a draft is generating, suppress all
// user mutation paths (form submit, inline edit, completion toggle,
// delete, drag, gap-click-to-add, command bar). Provided via inject so
// child components don't need to thread it through props.
const scheduleDisabled = computed(() => isGeneratingDraft.value)
provide("scheduleDisabled", scheduleDisabled)

const {
  isDragging, dragBlockId, ghostTop, previewStartTime, previewEndTime,
  previewBlocks, shiftedBlockIds, startDrag, endDrag, cancelDrag,
} = useDrag(
  () => props.date, getBlocks, reorderBlocks, pushUndo, snapshotBlocks,
  () => scheduleDisabled.value,
)

// Provide to child components
provide("undo", { pushUndo, snapshotBlocks })
provide("drag", { startDrag, isDragging, dragBlockId, shiftedBlockIds })
provide("scheduleContainer", scheduleBodyRef)

// Multi-turn chat thread (feature 0007). State lives in `useChat`
// (module-level) so the bottom dock and the sidebar variant share one
// thread. Re-anchor the active date here so navigation between days
// always resets the thread — without this, a follow-up like "ага,
// добавь его" authored against day A could mutate day B. The watcher is
// `immediate: true` so first mount registers the date too.
const { setActiveDate: setChatActiveDate } = useChat()
watch(
  () => props.date,
  (d) => setChatActiveDate(d),
  { immediate: true },
)

// Feature 0008 — viewport-driven chat surface choice.
// Wide (≥1024px) → ChatSidebar (right-hand panel, controlled open
// state); narrow → CommandBar dock. `useChat` is module-level so the
// active thread survives the switch.
const { isWide } = useViewport()
const sidebarOpen = ref<boolean>(readChatSidebarOpen())
watch(sidebarOpen, writeChatSidebarOpen)

const chatSidebarWidth = computed(() => {
  if (!isWide.value) return "0px"
  return sidebarOpen.value ? "380px" : "32px"
})

const schedulePageStyle = computed(() => ({
  "--chat-sidebar-width": chatSidebarWidth.value,
}))

// Per-component-instance set of dates the auto-draft has already been
// attempted for. Inertia's same-component navigation sometimes preserves
// state and only refreshes props (partial reload), and partial reloads
// explicitly do not remount, so onMounted is unreliable for "fire once
// per new date." A watcher with this set covers first mount AND date
// navigation reliably; a real remount (full Inertia visit) starts fresh,
// which is correct: the server's `auto_draft_pending` is the
// authoritative one-shot signal for "this is a brand-new schedule."
const attemptedAutoDraftDates = new Set<string>()

async function maybeGenerateDraft() {
  if (
    !props.auto_draft_pending ||
    props.blocks.length !== 0 ||
    attemptedAutoDraftDates.has(props.date)
  ) {
    return
  }
  attemptedAutoDraftDates.add(props.date)
  await runDraft()
}

watch(
  () => [props.date, props.auto_draft_pending, props.blocks.length] as const,
  () => {
    maybeGenerateDraft()
  },
  { immediate: true },
)

async function runDraft() {
  const snapshot = snapshotBlocks()
  // Bind undo to the date active when the draft request starts — if the
  // user navigates dates while the LLM call is in flight, ``props.date``
  // would shift and undo would restore this day's empty snapshot onto a
  // different date. Issue #21.
  const scheduleDate = props.date
  const result = await generateDraft(scheduleDate)
  if (result.ok) {
    pushUndo({
      description: result.explanation || "Generated draft",
      type: "draft",
      previousBlocks: snapshot,
      scheduleDate,
    })
  }
}

function handleRegenerateClick() {
  runDraft()
}

const isToday = computed(() => props.date === todayString())

// Analytics is past-/today-only AND meaningless on a never-edited
// (draft) day — analytics_view returns 400 for future and 404 for
// missing schedules, but a stale link in the nav would still feel
// broken. Hide it locally for those cases.
const showAnalyticsLink = computed(() => {
  return props.date <= todayString() && props.schedule.status !== "draft"
})

// Reactive current-minute counter so display list recomputes as time passes
const NOW_UPDATE_INTERVAL_MS = 60_000
const nowMinutes = ref(getCurrentMinutes())
let nowInterval: ReturnType<typeof setInterval> | null = null

function getCurrentMinutes(): number {
  const now = new Date()
  return now.getHours() * 60 + now.getMinutes()
}

onMounted(() => {
  if (!isToday.value) return
  nowInterval = setInterval(() => {
    nowMinutes.value = getCurrentMinutes()
  }, NOW_UPDATE_INTERVAL_MS)
})

onUnmounted(() => {
  if (nowInterval) clearInterval(nowInterval)
})

// During drag, use preview blocks for real-time visual feedback
const effectiveBlocks = computed(() =>
  isDragging.value && previewBlocks.value.length > 0
    ? previewBlocks.value
    : props.blocks,
)

// Ghost element computed properties
const draggedBlock = computed(() =>
  dragBlockId.value !== null
    ? props.blocks.find((b) => b.id === dragBlockId.value)
    : null,
)
const ghostHeight = computed(() => {
  if (!draggedBlock.value) return 0
  const dur = timeToMinutes(draggedBlock.value.end_time) - timeToMinutes(draggedBlock.value.start_time)
  return dur * PX_PER_MINUTE
})
const ghostIsCompact = computed(() => {
  if (!draggedBlock.value) return false
  const dur = timeToMinutes(draggedBlock.value.end_time) - timeToMinutes(draggedBlock.value.start_time)
  return dur <= 30
})

// Build the display list: blocks and gaps with the now marker spliced in.
const displayList = computed<DisplayItem[]>(() => {
  const blocks = effectiveBlocks.value
  const baseItems: RenderItem[] = []

  // Filter blocks to those overlapping the visible day window
  const visibleBlocks = blocks.filter(
    (b) => timeToMinutes(b.end_time) > DAY_START_MINUTES && timeToMinutes(b.start_time) < DAY_END_MINUTES
  )

  if (visibleBlocks.length === 0) {
    baseItems.push({
      type: "gap",
      start_time: DAY_START,
      end_time: DAY_END,
      duration_minutes: DAY_END_MINUTES - DAY_START_MINUTES,
    })
  } else {
    // Gap before first block
    const firstStart = Math.max(timeToMinutes(visibleBlocks[0].start_time), DAY_START_MINUTES)
    if (firstStart > DAY_START_MINUTES) {
      baseItems.push({
        type: "gap",
        start_time: DAY_START,
        end_time: minutesToTime(firstStart),
        duration_minutes: firstStart - DAY_START_MINUTES,
      })
    }

    for (let i = 0; i < visibleBlocks.length; i++) {
      const block = visibleBlocks[i]
      const clampedStart = Math.max(timeToMinutes(block.start_time), DAY_START_MINUTES)
      const clampedEnd = Math.min(timeToMinutes(block.end_time), DAY_END_MINUTES)
      baseItems.push({
        type: "block",
        block,
        start_time: minutesToTime(clampedStart),
        end_time: minutesToTime(clampedEnd),
        duration_minutes: clampedEnd - clampedStart,
      })

      if (i < visibleBlocks.length - 1) {
        const gapStart = clampedEnd
        const nextStart = Math.max(timeToMinutes(visibleBlocks[i + 1].start_time), DAY_START_MINUTES)
        const gapMinutes = nextStart - gapStart
        if (gapMinutes > 0) {
          baseItems.push({
            type: "gap",
            start_time: minutesToTime(gapStart),
            end_time: minutesToTime(nextStart),
            duration_minutes: gapMinutes,
          })
        }
      }
    }

    // Gap after last block
    const lastEnd = Math.min(timeToMinutes(visibleBlocks[visibleBlocks.length - 1].end_time), DAY_END_MINUTES)
    if (lastEnd < DAY_END_MINUTES) {
      baseItems.push({
        type: "gap",
        start_time: minutesToTime(lastEnd),
        end_time: DAY_END,
        duration_minutes: DAY_END_MINUTES - lastEnd,
      })
    }
  }

  // If not today, return as-is (no now marker)
  if (!isToday.value) {
    return baseItems as DisplayItem[]
  }

  // Splice the now marker into the list
  const now = nowMinutes.value
  const result: DisplayItem[] = []
  let inserted = false

  for (const item of baseItems) {
    const start = timeToMinutes(item.start_time)
    const end = timeToMinutes(item.end_time)

    if (inserted || now < start || now >= end) {
      // Current time is not in this item — pass through
      result.push(item as DisplayItem)
      continue
    }

    inserted = true

    if (item.type === "gap") {
      // Gap with now overlay — keeps the full gap height intact
      result.push({
        ...item,
        type: "gap-with-now",
      } as DisplayItem)
    } else {
      // Block with now overlay
      result.push({
        ...item,
        type: "block-with-now",
      } as DisplayItem)
    }
  }

  return result
})

function itemHeight(item: DisplayItem): string {
  return `${item.duration_minutes * PX_PER_MINUTE}px`
}

function nowOffsetPercent(item: DisplayItem): string {
  const start = timeToMinutes(item.start_time)
  const end = timeToMinutes(item.end_time)
  const span = end - start
  if (span <= 0) return "0%"
  return ((nowMinutes.value - start) / span) * 100 + "%"
}

function handleAddHere(payload: { start_time: string; end_time: string }) {
  prefillStart.value = payload.start_time
  prefillEnd.value = payload.end_time
}

function logout() {
  router.post("/accounts/logout/")
}
</script>

<template>
  <div class="schedule-page" :style="schedulePageStyle">
    <DateNavigator :date="date">
      <template #status>
        <DraftBadge
          :show="schedule.status === 'draft' && blocks.length > 0"
        />
      </template>
      <template #actions>
        <RegenerateDraftButton
          v-if="schedule.status === 'draft' && blocks.length === 0"
          :has-template="has_template_for_type"
          :slot-type="slot_type"
          @click="handleRegenerateClick"
        />
        <Link
          v-if="showAnalyticsLink"
          :href="`/analytics/${date}/`"
          class="analytics-link"
        >
          View analytics
        </Link>
      </template>
    </DateNavigator>

    <p v-if="lastDraftError" class="draft-error">{{ lastDraftError }}</p>

    <AddBlockForm
      :date="date"
      :initial-start-time="prefillStart"
      :initial-end-time="prefillEnd"
    />

    <div
      ref="scheduleBodyRef"
      class="schedule-body"
      :class="{ 'has-dock': !isWide }"
    >
      <div v-if="isGeneratingDraft" class="draft-overlay" aria-live="polite">
        <span class="overlay-spinner" />
        <span class="overlay-text">Generating draft…</span>
      </div>
      <!-- Drag ghost element -->
      <div
        v-if="isDragging && draggedBlock"
        class="drag-ghost"
        :class="{ compact: ghostIsCompact }"
        :style="{ top: ghostTop + 'px', height: ghostHeight + 'px' }"
      >
        <span class="ghost-handle">&#x2807;</span>
        <template v-if="ghostIsCompact">
          <input type="checkbox" class="ghost-checkbox" disabled />
          <span class="ghost-time">{{ previewStartTime }}–{{ previewEndTime }}</span>
          <span class="ghost-title">{{ draggedBlock.title }}</span>
        </template>
        <template v-else>
          <div class="ghost-header">
            <span class="ghost-time">{{ previewStartTime }} – {{ previewEndTime }}</span>
          </div>
          <div class="ghost-body">
            <input type="checkbox" class="ghost-checkbox" disabled />
            <span class="ghost-title">{{ draggedBlock.title }}</span>
          </div>
        </template>
      </div>

      <template v-for="(item, idx) in displayList" :key="idx">
        <div
          v-if="item.type === 'block-with-now' && item.block"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <TimeBlock :block="item.block" :date="date" />
          <NowLine
            class="now-overlay"
            :style="{ top: nowOffsetPercent(item) }"
          />
        </div>

        <div
          v-else-if="item.type === 'gap-with-now'"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <GapSlot
            :start-time="item.start_time"
            :end-time="item.end_time"
            :duration-minutes="item.duration_minutes"
            :disabled="scheduleDisabled"
            @add-here="handleAddHere"
          />
          <NowLine
            class="now-overlay"
            :style="{ top: nowOffsetPercent(item) }"
          />
        </div>

        <div
          v-else-if="(item.type === 'block') && item.block"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <TimeBlock :block="item.block" :date="date" />
        </div>

        <div
          v-else-if="item.type === 'gap'"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <GapSlot
            :start-time="item.start_time"
            :end-time="item.end_time"
            :duration-minutes="item.duration_minutes"
            :disabled="scheduleDisabled"
            @add-here="handleAddHere"
          />
        </div>
      </template>
    </div>

    <div class="logout-footer">
      <button class="logout-btn" @click="logout">Logout</button>
    </div>

    <UndoToast
      v-if="currentToast"
      :message="currentToast.description"
      :actionable="currentToast.actionable"
      @undo="performUndo"
      @dismiss="dismissToast"
    />

    <ChatSidebar
      v-if="isWide"
      v-model:open="sidebarOpen"
      :date="date"
      :snapshot-blocks="snapshotBlocks"
      :push-undo="pushUndo"
    />
    <CommandBar
      v-else
      :date="date"
      :snapshot-blocks="snapshotBlocks"
      :push-undo="pushUndo"
      variant="dock"
    />
  </div>
</template>

<style scoped>
.schedule-page {
  /* Explicit content-box so `padding-right: var(--chat-sidebar-width)`
     extends the page width without eating into the 640px content area.
     The global `*` reset in app.css sets border-box; this is a scoped
     override. */
  box-sizing: content-box;
  max-width: 640px;
  margin: 0 auto;
  min-height: 100vh;
  background: var(--bg-schedule-gap);
  padding-right: var(--chat-sidebar-width, 0);
}

.schedule-body {
  position: relative;
  padding: 8px 16px;
}

/* Bottom padding only when the fixed dock is rendered (narrow viewport);
   wide screens use the sidebar and don't need to clear the dock. */
.schedule-body.has-dock {
  padding-bottom: 88px;
}

.draft-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  /* Theme-aware overlay: a softened wash of the page background so the
     overlay text (theme-token foreground) is always readable. Avoids
     adding a new --draft-overlay-bg token without breaking the P4 freeze. */
  background: color-mix(in srgb, var(--bg-page) 85%, transparent);
  z-index: 25;
  font-size: 14px;
  color: var(--text-secondary);
  pointer-events: auto;
}

.overlay-spinner {
  width: 24px;
  height: 24px;
  /* Track uses the theme's strong-border token so it remains visible
     against both light and dark overlay washes. */
  border: 3px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.overlay-text {
  font-weight: 500;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.draft-error {
  max-width: 640px;
  margin: 0 auto;
  padding: 8px 16px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 8px;
  font-size: 13px;
}

.drag-ghost {
  position: absolute;
  left: 16px;
  right: 16px;
  background: rgba(59, 130, 246, 0.12);
  border: 2px dashed #3b82f6;
  border-radius: 8px;
  padding: 12px 16px 12px 34px;
  pointer-events: none;
  z-index: 20;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  box-sizing: border-box;
  overflow: hidden;
}

.drag-ghost.compact {
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  padding: 4px 8px 4px 30px;
  gap: 8px;
}

.ghost-handle {
  position: absolute;
  left: 4px;
  top: 0;
  bottom: 0;
  width: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #93c5fd;
  font-size: 16px;
}

.ghost-header {
  display: flex;
  align-items: center;
  gap: 8px;
  /* Match block-header height (driven by its 24px delete-btn) so the
     body (checkbox + title) lands at the same y as in the real block. */
  height: 24px;
}

.ghost-body {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.ghost-checkbox {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  pointer-events: none;
}

.drag-ghost.compact .ghost-checkbox {
  width: 14px;
  height: 14px;
}

.ghost-time {
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
  flex-shrink: 0;
}

.drag-ghost.compact .ghost-time {
  font-size: 12px;
}

.ghost-title {
  font-size: 15px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drag-ghost.compact .ghost-title {
  font-size: 13px;
}

.schedule-slot {
  position: relative;
  overflow: visible;
}

.now-overlay {
  position: absolute;
  left: 0;
  right: 0;
  z-index: 10;
  transform: translateY(-50%);
}

.logout-footer {
  padding: 24px 16px;
  text-align: right;
}

.logout-btn {
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--bg-panel);
  color: var(--text-muted);
  cursor: pointer;
}

.logout-btn:hover {
  background: var(--danger-surface);
  color: var(--danger-text);
  border-color: var(--danger-border);
}

.analytics-link {
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--bg-panel);
  color: var(--text-secondary);
  text-decoration: none;
}

.analytics-link:hover {
  background: var(--bg-schedule-gap);
  color: var(--text-primary);
}
</style>
