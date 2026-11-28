<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, provide, toRef, watch } from "vue"
import { Link, router } from "@inertiajs/vue3"
import type { TimeBlock as TimeBlockType, Schedule, ScheduleSettingsWire, UserCategory } from "../types"
import TimeZoneMismatchPrompt from "../components/TimeZoneMismatchPrompt.vue"
import DateNavigator from "../components/DateNavigator.vue"
import TimeBlock from "../components/TimeBlock.vue"
import Timeline4a from "../components/Timeline4a.vue"
import TimelineMobile from "../components/TimelineMobile.vue"
import EmptyDayState from "../components/EmptyDayState.vue"
import GapSlot from "../components/GapSlot.vue"
import AddBlockForm from "../components/AddBlockForm.vue"
import NowLine from "../components/NowLine.vue"
import UndoToast from "../components/UndoToast.vue"
import CommandBar from "../components/CommandBar.vue"
import ChatSidebar from "../components/ChatSidebar.vue"
import ExternalTasksSidebar from "../components/ExternalTasksSidebar.vue"
import ExternalRail4a from "../components/ExternalRail4a.vue"
import DraftBadge from "../components/DraftBadge.vue"
import RegenerateDraftButton from "../components/RegenerateDraftButton.vue"
import ShowIndicatorButton from "../components/ShowIndicatorButton.vue"
import MobileHeader from "../components/MobileHeader.vue"
import MobileCalendarsSheet from "../components/MobileCalendarsSheet.vue"
import MobileFab from "../components/MobileFab.vue"
import ExternalEventsPanel from "../components/ExternalEventsPanel.vue"
import AddToScheduleDialog from "../components/AddToScheduleDialog.vue"
import { FocusIndicatorControllerKey, useFocusIndicatorController } from "../composables/useFocusIndicatorController"
import { useIsMobile, useViewport } from "../composables/useViewport"
import { readChatSidebarOpen, writeChatSidebarOpen } from "../utils/chatSidebarStorage"
import { readExternalTasksSidebarOpen, writeExternalTasksSidebarOpen } from "../utils/externalTasksSidebarStorage"
import { timeToMinutes, type ScheduleWindowBounds } from "../utils/scheduleTime"
import { useSchedulePageController } from "../composables/useSchedulePageController"
import { MOBILE_TOAST_DURATION_MS, TOAST_DURATION_MS } from "../composables/useUndo"
import { ScheduleDragKey, ScheduleContainerKey } from "../composables/scheduleContext"
import { useDrag } from "../composables/useDrag"
import { useTimelinePresentation } from "../composables/useTimelinePresentation"
import { useExternalSources } from "../composables/useExternalSources"
import { useEventImport, type IntegrationBootstrap } from "../composables/useEventImport"
import { useThemeFromProps } from "../composables/useThemeFromProps"
import { useActiveTheme } from "../composables/useActiveTheme"
import { layoutForTheme, pxPerMinuteForLayout } from "../utils/layoutProfile"
import { useNowMinutes } from "../composables/useNowMinutes"
import { useSoundNotifications } from "../composables/useSoundNotifications"
import { useDesktopNotifications } from "../composables/useDesktopNotifications"
import { useExternalCalendarPlacement } from "../composables/useExternalCalendarPlacement"
import { hasValidCategoryCatalog } from "../utils/categories"
import "../app.css"

useThemeFromProps()
const activeTheme = useActiveTheme()
const layout = computed(() => layoutForTheme(activeTheme.value))
// Dark 4a at max-width 640 px (feature 0113). Other themes and wider screens
// keep the header and panels unchanged.
const { isMobile } = useIsMobile()
const mobileLayout = computed(() => layout.value === "4a" && isMobile.value)
const pxPerMinute = computed(() => pxPerMinuteForLayout(layout.value))
const props = withDefaults(defineProps<{
  auth_user_id?: number | null
  schedule: Schedule
  blocks: TimeBlockType[]
  categories: UserCategory[]
  date: string
  auto_draft_pending?: boolean
  has_template_for_type?: boolean
  slot_type?: "weekday" | "weekend"
  external_tasks_poll_interval?: number
  schedule_window?: ScheduleSettingsWire
  integration_bootstrap?: IntegrationBootstrap
}>(), {
  auto_draft_pending: false,
  has_template_for_type: false,
  slot_type: "weekday",
  external_tasks_poll_interval: 60,
  schedule_window: () => ({ start: "06:00", end: "23:00", time_zone: "UTC" }),
})
const categoryCatalogValid = computed(() => hasValidCategoryCatalog(props.categories))
const prefillStart = ref<string | undefined>()
const prefillEnd = ref<string | undefined>()
const scheduleBodyRef = ref<HTMLElement | null>(null)
const scheduleWindow = computed<ScheduleWindowBounds>(() => ({
  start: props.schedule_window.start,
  end: props.schedule_window.end,
  startMinutes: timeToMinutes(props.schedule_window.start),
  endMinutes: timeToMinutes(props.schedule_window.end),
}))
const scheduleTimeZone = computed(() => props.schedule_window.time_zone)
const {
  scheduleRevision, canonicalBlocks, canonicalSchedule, getBlocks, reorderBlocks,
  isGeneratingDraft, lastDraftError, scheduleDisabled,
  canUndo, currentToast, pushUndo, performUndo, snapshotBlocks, dismissToast,
  handleRegenerateClick, resetSession,
} = useSchedulePageController({
  getDate: () => props.date,
  getSchedule: () => props.schedule,
  getBlocks: () => props.blocks,
  getUserId: () => props.auth_user_id,
  getTimeZone: () => props.schedule_window.time_zone,
  getAutoDraftPending: () => props.auto_draft_pending && categoryCatalogValid.value,
  getMutationsDisabled: () => !categoryCatalogValid.value,
  getToastDurationMs: () => mobileLayout.value ? MOBILE_TOAST_DURATION_MS : TOAST_DURATION_MS,
})

// One saved-zone clock supplies presentation, notifications and the PiP owner.
const { nowMinutes, nowDate, todayDate, currentHHMM } = useNowMinutes(toRef(props, "date"), scheduleTimeZone)
const todayNowMinutes = computed(() => nowDate.value === null ? null : nowMinutes.value)
let drag: ReturnType<typeof useDrag> | undefined
const {
  renderBounds, timelineOriginMinutes, effectiveBlocks,
  currentBlock, currentBlockRemaining, displayList, ghostHeight, ghostDuration, axisMap,
  itemHeight, nowOffsetPercent, presentation,
} = useTimelinePresentation({
  getBlocks,
  getDate: () => props.date,
  getWindow: () => scheduleWindow.value,
  getNowMinutes: () => nowMinutes.value,
  getNowDate: () => nowDate.value,
  getPxPerMinute: () => pxPerMinute.value,
  // Dark 4a stacks the column (feature 0106); classic keeps the linear flow.
  getLayoutMode: () => layout.value === "4a" ? "stack" : "linear",
  getDragState: () => drag ? {
    isDragging: drag.isDragging.value,
    previewBlocks: drag.previewBlocks.value,
    dragBlockId: drag.dragBlockId.value,
    frozenRenderBounds: drag.frozenRenderBounds.value,
    frozenNowMinutes: drag.frozenNowMinutes.value,
    frozenPxPerMinute: drag.frozenPxPerMinute.value,
    frozenTimelineOriginMinutes: drag.frozenTimelineOriginMinutes.value,
    frozenWindow: drag.frozenWindow.value,
  } : null,
})
drag = useDrag(
  () => props.date, getBlocks, reorderBlocks, pushUndo, snapshotBlocks,
  () => scheduleDisabled.value, () => renderBounds.value,
  () => todayNowMinutes.value, () => scheduleWindow.value,
  () => pxPerMinute.value,
  () => layout.value === "4a" ? timelineOriginMinutes.value : null,
  () => `${props.date}|${props.schedule_window.time_zone}|${activeTheme.value}`,
  () => layout.value === "4a" ? axisMap.value : null,
  () => mobileLayout.value,
)
const {
  isDragging, dragBlockId, ghostTop, previewStartTime, previewEndTime, shiftedBlockIds, startDrag,
  previewBlocks, dropInvalid,
} = drag
watch(categoryCatalogValid, (valid) => {
  if (!valid && drag?.isDragging.value) drag.cancelDrag()
}, { flush: "sync" })
provide(ScheduleDragKey, { startDrag, isDragging, dragBlockId, shiftedBlockIds, previewBlocks })
provide(ScheduleContainerKey, scheduleBodyRef)
const draggedBlock = computed(() => canonicalBlocks.value.find(block => block.id === dragBlockId.value) ?? null)

const { isWide } = useViewport()
const mobileCalendarsOpen = ref(false)
const mobileHeaderRef = ref<InstanceType<typeof MobileHeader> | null>(null)
watch(mobileLayout, (on) => { if (!on) mobileCalendarsOpen.value = false })
const chatDockHeight = ref(0)
const sidebarOpen = ref(readChatSidebarOpen())
watch(sidebarOpen, writeChatSidebarOpen)
const externalTasksSidebarOpen = ref(readExternalTasksSidebarOpen())
watch(externalTasksSidebarOpen, writeExternalTasksSidebarOpen)
const { placement: storedCalendarPlacement } = useExternalCalendarPlacement()
// Below 1024 px the rails unmount. In Dark 4a the calendar panel then falls
// back to the centre position (under the timeline) so its explicit
// "Add to schedule" stays reachable; the stored preference is not rewritten
// (feature 0106). Rendering and polling both read this one value.
const narrow4aCalendar = computed(() => layout.value === "4a" && !isWide.value)
const externalCalendarPlacement = computed(() =>
  narrow4aCalendar.value ? "center" as const : storedCalendarPlacement.value)
const {
  googleCalendar, todoist, habitica,
  mergedExternalEvents, externalConnected, externalLoading, externalErrorBanners,
  retryExternalFetch, retryTodoistTasks, completeTodoistTask,
  retryHabiticaTasks, completeHabiticaTask, refreshExternalTasks, refreshExternalCalendars,
  externalCalendarInSidebar, externalCalendarInCenter, externalCalendarVisible,
  tasksBranch, calendarsBranch, externalPollActive, leftSidebarVisible,
} = useExternalSources({
  date: toRef(props, "date"), timeZone: scheduleTimeZone, todayDate,
  userId: toRef(props, "auth_user_id"), bootstrap: toRef(props, "integration_bootstrap"),
  isWide, sidebarOpen: externalTasksSidebarOpen, placement: externalCalendarPlacement,
  pollIntervalSeconds: toRef(props, "external_tasks_poll_interval"),
})
const { addDialogEvent, addDialogRule, travelRulesError, handleAddToSchedule, closeAddDialog } = useEventImport({
  date: toRef(props, "date"), timeZone: scheduleTimeZone,
  userId: toRef(props, "auth_user_id"), bootstrap: toRef(props, "integration_bootstrap"),
})
const schedulePageStyle = computed(() => ({
  "--chat-dock-height": isWide.value ? "0px" : `${chatDockHeight.value}px`,
  "--chat-sidebar-width": !isWide.value ? "0px" : sidebarOpen.value ? "380px" : "32px",
  "--external-tasks-sidebar-width": !isWide.value || !leftSidebarVisible.value
    ? "0px" : externalTasksSidebarOpen.value ? "380px" : "32px",
}))
const showAnalyticsLink = computed(() => props.date <= todayDate.value && canonicalSchedule.value?.status !== "draft")
useSoundNotifications(nowMinutes, nowDate, getBlocks)
useDesktopNotifications(nowMinutes, nowDate, getBlocks)

// PiP is owned by the application root and survives page navigation.
const focusIndicatorController = inject(FocusIndicatorControllerKey, null) ?? useFocusIndicatorController()
const focusIndicatorGeneration = focusIndicatorController.publicationGeneration()
watch([() => props.date, effectiveBlocks, () => props.categories, scheduleTimeZone], ([date, blocks]) => {
  focusIndicatorController.publishIfGenerationMatches(
    focusIndicatorGeneration,
    date,
    blocks,
    categoryCatalogValid.value ? props.categories : [],
    scheduleTimeZone.value,
  )
}, { immediate: true, deep: true })
onBeforeUnmount(() => {
  focusIndicatorController.publishIfGenerationMatches(
    focusIndicatorGeneration,
    props.date,
    canonicalBlocks.value,
    categoryCatalogValid.value ? props.categories : [],
    scheduleTimeZone.value,
  )
})
const focusIndicator = focusIndicatorController.focusIndicator
const indicatorActive = focusIndicatorController.indicatorActive
const indicatorPercent = focusIndicatorController.indicatorPercent
const indicatorNextBlock = focusIndicatorController.indicatorNextBlock
const indicatorNextBlockTitle = focusIndicatorController.indicatorNextBlockTitle
const indicatorNextBlockRemaining = focusIndicatorController.indicatorNextBlockRemaining
const indicatorPausePercent = focusIndicatorController.indicatorPausePercent
const indicatorDayFinished = focusIndicatorController.indicatorDayFinished
const focusIndicatorSupported = focusIndicator.supported
const focusIndicatorOpen = focusIndicator.isOpen
const focusIndicatorOpenError = focusIndicator.openError
const openFocusIndicator = focusIndicator.open
function handleAddHere(payload: { start_time: string; end_time: string }) {
  prefillStart.value = payload.start_time
  prefillEnd.value = payload.end_time
}
// Dark 4a day with no template and no blocks: an empty state replaces the
// timeline (feature 0106).
const showEmptyDay = computed(() =>
  layout.value === "4a" && !props.has_template_for_type &&
  canonicalBlocks.value.length === 0 && !isGeneratingDraft.value)
// "Plan with AI": open the wide chat sidebar and focus its input (or the dock
// below 1024 px). The chat clears the request once it has placed focus.
const chatFocusToken = ref(0)
function planWithAi() {
  if (isWide.value) sidebarOpen.value = true
  chatFocusToken.value += 1
}
function clearChatFocusRequest() {
  chatFocusToken.value = 0
}
// Dark 4a gap rows: a new request id reopens the form even when the same gap
// (same prefill) is activated again after Cancel.
const addRequestId = ref(0)
function handleAddHere4a(payload: { start_time: string; end_time: string }) {
  handleAddHere(payload)
  addRequestId.value += 1
}
// The phone FAB opens the add form with its default range (feature 0113).
function handleFab() {
  prefillStart.value = undefined
  prefillEnd.value = undefined
  addRequestId.value += 1
}
function logout() {
  resetSession()
  router.post("/accounts/logout/")
}
// Stable integration-test seams; production consumers use the controllers.
defineExpose({
  externalPollActive, externalCalendarVisible, tasksBranch, calendarsBranch,
  refreshExternalTasks, refreshExternalCalendars,
  focusIndicator, indicatorActive, indicatorPercent, indicatorNextBlock,
  indicatorNextBlockTitle, indicatorNextBlockRemaining, indicatorPausePercent, indicatorDayFinished,
})
</script>

<template>
  <div
    v-if="categoryCatalogValid"
    class="schedule-page"
    :class="{ 'layout-4a': layout === '4a' }"
    :style="schedulePageStyle"
  >
    <TimeZoneMismatchPrompt v-if="!mobileLayout" :time-zone="schedule_window.time_zone" />
    <MobileHeader
      v-if="mobileLayout"
      ref="mobileHeaderRef"
      :date="date"
      :show-analytics="showAnalyticsLink"
      :show-calendars="externalConnected"
      @calendars="mobileCalendarsOpen = true"
      @logout="logout"
    />
    <DateNavigator v-else :date="date" :today="todayDate">
      <template #status>
        <DraftBadge
          :show="canonicalSchedule?.status === 'draft' && canonicalBlocks.length > 0"
        />
      </template>
      <template #actions>
        <button
          type="button"
          class="undo-btn df-btn df-btn--secondary"
          aria-label="Undo last change"
          title="Undo last change (⌘Z / Ctrl+Z)"
          :disabled="!canUndo || scheduleDisabled"
          @click="performUndo"
        >Undo</button>
        <RegenerateDraftButton
          v-if="canonicalSchedule?.status === 'draft' && canonicalBlocks.length === 0"
          :has-template="has_template_for_type"
          :slot-type="slot_type"
          :show-reason="layout !== '4a'"
          @click="handleRegenerateClick"
        />
        <ShowIndicatorButton
          :supported="focusIndicatorSupported"
          :is-open="focusIndicatorOpen"
          :should-restore="focusIndicator.shouldRestore.value"
          :error="focusIndicatorOpenError"
          @open="openFocusIndicator"
          @close="focusIndicator.cleanup"
        />
        <Link
          v-if="showAnalyticsLink"
          :href="`/analytics/${date}/`"
          class="analytics-link df-btn df-btn--secondary"
        >
          View analytics
        </Link>
      </template>
    </DateNavigator>

    <p v-if="lastDraftError" class="draft-error">{{ lastDraftError }}</p>

    <ExternalEventsPanel
      :time-zone="schedule_window.time_zone"
      :today-date="todayDate"
      v-if="externalConnected && externalCalendarInCenter && !narrow4aCalendar"
      variant="center"
      :layout="layout"
      :date="date"
      :now-minutes="nowMinutes"
      :events="mergedExternalEvents"
      :loading="externalLoading"
      :error-banners="externalErrorBanners"
      :account-errors="googleCalendar.state.accountErrors"
      :connected="externalConnected"
      @retry="retryExternalFetch"
      @add-to-schedule="handleAddToSchedule"
    />

    <AddBlockForm
      :date="date"
      :initial-start-time="prefillStart"
      :initial-end-time="prefillEnd"
      :add-request-id="layout === '4a' ? addRequestId : undefined"
      :categories="categories"
      :mobile="mobileLayout"
    />

    <div
      ref="scheduleBodyRef"
      class="schedule-body"
    >
      <p v-if="scheduleRevision.synchronizing.value" class="schedule-sync-message" role="status">
        Updating schedule. Refresh the page if it does not finish.
      </p>
      <div v-if="isGeneratingDraft" class="draft-overlay" aria-live="polite">
        <span class="overlay-spinner" />
        <span class="overlay-text">Generating draft…</span>
      </div>
      <!-- Drag ghost element -->
      <div
        v-if="isDragging && draggedBlock && layout === '4a'"
        class="drag-ghost ghost-4a"
        :class="{ 'is-invalid': dropInvalid }"
        :style="{ top: ghostTop + 'px', height: ghostHeight + 'px' }"
        data-testid="drag-ghost-4a"
      >
        <span class="ghost-handle">&#x2807;</span>
        <input type="checkbox" class="ghost-checkbox df-checkbox" disabled />
        <span class="ghost-time">{{ previewStartTime }}</span>
        <span class="ghost-duration">{{ ghostDuration }}</span>
        <span class="ghost-title">{{ dropInvalid ? "Can't drop here" : draggedBlock.title }}</span>
      </div>
      <div
        v-else-if="isDragging && draggedBlock"
        class="drag-ghost"
        :style="{ top: ghostTop + 'px', height: ghostHeight + 'px' }"
      >
        <span class="ghost-handle">&#x2807;</span>
        <input type="checkbox" class="ghost-checkbox df-checkbox" disabled />
        <span class="ghost-time">{{ previewStartTime }}–{{ previewEndTime }}</span>
        <span class="ghost-duration">{{ ghostDuration }}</span>
        <span class="ghost-title">{{ draggedBlock.title }}</span>
      </div>

      <EmptyDayState
        v-if="showEmptyDay"
        :date="date"
        :slot-type="slot_type"
        @plan-with-ai="planWithAi"
      />
      <TimelineMobile
        v-else-if="mobileLayout"
        :blocks="canonicalBlocks"
        :window="scheduleWindow"
        :date="date"
        :disabled="scheduleDisabled"
        :categories="categories"
        @add-here-4a="handleAddHere4a"
      />
      <Timeline4a
        v-else-if="layout === '4a'"
        :presentation="presentation"
        :date="date"
        :current-h-h-m-m="currentHHMM"
        :disabled="scheduleDisabled"
        :categories="categories"
        @add-here-4a="handleAddHere4a"
      />

      <template v-if="layout === 'classic'" v-for="(item, idx) in displayList" :key="idx">
        <div
          v-if="item.type === 'block-with-now' && item.block"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <TimeBlock
            :block="item.block"
            :date="date"
            :is-current="item.block?.id === currentBlock?.id"
            :remaining-minutes="item.block?.id === currentBlock?.id ? currentBlockRemaining : null"
            :categories="categories"
          />
          <NowLine
            :label="currentHHMM"
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
            :compact="item.compact"
            :window-start="schedule_window.start"
            :disabled="scheduleDisabled"
            @add-here="handleAddHere"
          />
          <NowLine
            :label="currentHHMM"
            class="now-overlay"
            :style="{ top: nowOffsetPercent(item) }"
          />
        </div>

        <div
          v-else-if="(item.type === 'block') && item.block"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <TimeBlock
            :block="item.block"
            :date="date"
            :is-current="item.block?.id === currentBlock?.id"
            :remaining-minutes="item.block?.id === currentBlock?.id ? currentBlockRemaining : null"
            :categories="categories"
          />
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
            :compact="item.compact"
            :window-start="schedule_window.start"
            :disabled="scheduleDisabled"
            @add-here="handleAddHere"
          />
        </div>

        <!-- Inert spacer: out-of-window flow geometry only, not clickable. -->
        <div
          v-else-if="item.type === 'spacer'"
          class="schedule-slot schedule-spacer"
          :style="{ height: itemHeight(item) }"
          aria-hidden="true"
        />
      </template>
    </div>

    <ExternalEventsPanel
      v-if="externalConnected && externalCalendarInCenter && narrow4aCalendar && !mobileLayout"
      :time-zone="schedule_window.time_zone"
      :today-date="todayDate"
      variant="center"
      layout="4a"
      :date="date"
      :now-minutes="nowMinutes"
      :events="mergedExternalEvents"
      :loading="externalLoading"
      :error-banners="externalErrorBanners"
      :account-errors="googleCalendar.state.accountErrors"
      :connected="externalConnected"
      @retry="retryExternalFetch"
      @add-to-schedule="handleAddToSchedule"
    />

    <!-- Mobile: the calendar panel lives in the gear menu's Calendars sheet.
         The placement stays "center" below 1024 px, so polling is unchanged. -->
    <MobileCalendarsSheet
      v-if="mobileLayout && mobileCalendarsOpen"
      :fallback-focus="() => mobileHeaderRef?.$el?.querySelector('[data-testid=mobile-gear]') ?? null"
      @close="mobileCalendarsOpen = false"
    >
      <ExternalEventsPanel
        :time-zone="schedule_window.time_zone"
        :today-date="todayDate"
        variant="center"
        layout="4a"
        :date="date"
        :now-minutes="nowMinutes"
        :events="mergedExternalEvents"
        :loading="externalLoading"
        :error-banners="externalErrorBanners"
        :account-errors="googleCalendar.state.accountErrors"
        :connected="externalConnected"
        @retry="retryExternalFetch"
        @add-to-schedule="(event) => { mobileCalendarsOpen = false; handleAddToSchedule(event) }"
      />
    </MobileCalendarsSheet>

    <!-- Dark 4a moves Log out into Settings (feature 0106). -->
    <div v-if="layout !== '4a'" class="logout-footer">
      <button class="logout-btn" @click="logout">Logout</button>
    </div>

    <MobileFab v-if="mobileLayout" :disabled="scheduleDisabled" @click="handleFab" />

    <UndoToast
      v-if="currentToast"
      :message="currentToast.description"
      :actionable="currentToast.actionable && !scheduleDisabled"
      :mobile="mobileLayout"
      @undo="performUndo"
      @dismiss="dismissToast"
    />

    <ExternalRail4a
      :time-zone="schedule_window.time_zone"
      :today-date="todayDate"
      v-if="layout === '4a' && isWide && leftSidebarVisible"
      v-model:open="externalTasksSidebarOpen"
      :active-date="date"
      :show-todoist="todoist.state.statusKnown && todoist.state.connected"
      :show-habitica="habitica.state.statusKnown && habitica.state.connected"
      :show-calendars="externalConnected && externalCalendarInSidebar"
      :todoist-tasks="todoist.state.tasks"
      :todoist-loading="todoist.state.loading"
      :todoist-error="todoist.state.error"
      :habitica-tasks="habitica.state.tasks"
      :habitica-loading="habitica.state.loading"
      :habitica-error="habitica.state.error"
      :events="mergedExternalEvents"
      :events-loading="externalLoading"
      :event-errors="externalErrorBanners"
      :account-errors="googleCalendar.state.accountErrors"
      :external-connected="externalConnected"
      :now-minutes="nowMinutes"
      @todoist-retry="retryTodoistTasks"
      @todoist-complete="completeTodoistTask"
      @habitica-retry="retryHabiticaTasks"
      @habitica-complete="completeHabiticaTask"
      @refresh="refreshExternalTasks"
      @retry-external="retryExternalFetch"
      @add-to-schedule="handleAddToSchedule"
    />
    <ExternalTasksSidebar
      v-if="layout === 'classic' && isWide && leftSidebarVisible"
      v-model:open="externalTasksSidebarOpen"
      :show-todoist="todoist.state.statusKnown && todoist.state.connected"
      :show-habitica="habitica.state.statusKnown && habitica.state.connected"
      :show-extra="externalConnected && externalCalendarInSidebar"
      :todoist-tasks="todoist.state.tasks"
      :todoist-loading="todoist.state.loading"
      :todoist-error="todoist.state.error"
      :habitica-tasks="habitica.state.tasks"
      :habitica-loading="habitica.state.loading"
      :habitica-error="habitica.state.error"
      @todoist-retry="retryTodoistTasks"
      @todoist-complete="completeTodoistTask"
      @habitica-retry="retryHabiticaTasks"
      @habitica-complete="completeHabiticaTask"
      @refresh="refreshExternalTasks"
    >
      <!-- External-calendar panel (feature 0022): stacked under the Todoist
           list inside the left sidebar. Wide-screen only. -->
      <ExternalEventsPanel
      :time-zone="schedule_window.time_zone"
      :today-date="todayDate"
        v-if="externalCalendarInSidebar"
        variant="sidebar"
        :date="date"
        :now-minutes="nowMinutes"
        :events="mergedExternalEvents"
        :loading="externalLoading"
        :error-banners="externalErrorBanners"
        :account-errors="googleCalendar.state.accountErrors"
        :connected="externalConnected"
        @retry="retryExternalFetch"
        @add-to-schedule="handleAddToSchedule"
      />
    </ExternalTasksSidebar>
    <AddToScheduleDialog
      :time-zone="schedule_window.time_zone"
      v-if="addDialogEvent"
      :event="addDialogEvent"
      :matched-rule="addDialogRule"
      :date="date"
      :rules-unavailable="travelRulesError"
      :window="scheduleWindow"
      :categories="categories"
      :mobile="mobileLayout"
      @close="closeAddDialog"
    />
    <ChatSidebar
      v-if="isWide"
      v-model:open="sidebarOpen"
      :date="date"
      :push-undo="pushUndo"
      :focus-token="chatFocusToken"
      @focus-handled="clearChatFocusRequest"
    />
    <CommandBar
      v-else
      :date="date"
      :push-undo="pushUndo"
      :focus-token="chatFocusToken"
      variant="dock"
      :mobile="mobileLayout"
      @height-change="chatDockHeight = $event"
      @focus-handled="clearChatFocusRequest"
    />
  </div>
  <div v-else class="schedule-page" role="alert">
    Category data could not be loaded. <a href="">Reload the page</a> to try again.
  </div>
</template>

<style scoped>
.schedule-page {
  /* Explicit content-box so side padding extends page width without
     eating into the 640px content area. The global `*` reset in app.css
     sets border-box; this is a scoped override. */
  box-sizing: content-box;
  max-width: 640px;
  margin: 0 auto;
  min-height: 100vh;
  background: var(--bg-schedule-gap);
  padding-right: var(--chat-sidebar-width, 0);
  padding-left: var(--external-tasks-sidebar-width, 0);
  /* Reserve the dock's actual height after all content, including Logout. */
  padding-bottom: var(--chat-dock-height, 0px);
}

/* Center 4a inside the viewport space left after both fixed rails. The legacy
   content-box padding approach makes the content itself shrink and shifts its
   midpoint when a rail is open, so 4a uses explicit width/offset geometry. */
.schedule-page.layout-4a {
  --timeline-4a-axis-gutter: 48px;
  --timeline-4a-item-inset: 12px;
  box-sizing: border-box;
  width: min(
    880px,
    calc(
      100vw - var(--external-tasks-sidebar-width, 0px) -
        var(--chat-sidebar-width, 0px)
    )
  );
  max-width: 880px;
  margin-left: calc(
    var(--external-tasks-sidebar-width, 0px) +
      max(
        0px,
        (
            100vw - var(--external-tasks-sidebar-width, 0px) -
              var(--chat-sidebar-width, 0px) - 880px
          ) / 2
      )
  );
  margin-right: 0;
  padding-left: 0;
  padding-right: 0;
}

.undo-btn {
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-panel);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}

.undo-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.undo-btn:hover:not(:disabled) {
  background: var(--bg-schedule-gap);
}

.schedule-body {
  position: relative;
  padding: 8px 16px;
}

.schedule-sync-message {
  color: var(--text-secondary);
  font-size: 13px;
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
  overflow-wrap: anywhere;
  margin: 0 auto;
  padding: 8px 16px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 8px;
  font-size: 13px;
}

.schedule-page.layout-4a .draft-error {
  max-width: 880px;
}

.schedule-page.layout-4a :deep(.date-display) {
  align-items: flex-start;
  text-align: left;
}

.drag-ghost {
  position: absolute;
  left: 16px;
  right: 16px;
  background: rgba(59, 130, 246, 0.12);
  border: 2px dashed #3b82f6;
  border-radius: 8px;
  /* Mirrors TimeBlock.vue's single row: `.time-block` padding (+2px left for
     the dashed border), `.block-row` gap, `.checkbox` size, `.time-badge`,
     `.duration` and `.title` text. Change both files together. */
  padding: 4px 8px 4px 30px;
  pointer-events: none;
  z-index: 20;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
  gap: 8px;
  box-sizing: border-box;
  overflow: hidden;
}

/* 4a ghost: 16px body padding + gutter + item inset (classic is padding-only). */
.schedule-page.layout-4a .drag-ghost {
  left: calc(16px + var(--timeline-4a-axis-gutter) + var(--timeline-4a-item-inset));
}

/* Dark 4a ghost mirrors the compact row: one centred 13 px line inside the
   dragged item's stacked height (feature 0106). */
.drag-ghost.ghost-4a {
  padding: 0 8px 0 30px;
  background: color-mix(in oklab, var(--accent) 14%, var(--bg-schedule-block));
  border: 1px dashed var(--accent);
  box-shadow: var(--shadow-card);
  line-height: 16px;
}

.drag-ghost.ghost-4a .ghost-handle {
  color: var(--text-secondary);
}

.drag-ghost.ghost-4a .ghost-time,
.drag-ghost.ghost-4a .ghost-duration,
.drag-ghost.ghost-4a .ghost-title {
  font-size: 13px;
}

.drag-ghost.ghost-4a .ghost-duration {
  color: var(--text-secondary);
}

.drag-ghost.ghost-4a.is-invalid {
  background: var(--danger-surface);
  border-color: var(--danger-border);
}

.drag-ghost.ghost-4a.is-invalid .ghost-title {
  color: var(--danger-text);
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

.ghost-checkbox {
  pointer-events: none;
}

.ghost-time {
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
  flex-shrink: 0;
}

.ghost-duration {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-faint);
}

.ghost-title {
  min-width: 0;
  font-size: 14px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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

/* Dark 4a text floor (feature 0106): nothing below 13 px. */
html[data-theme="dark_4a"] .analytics-link {
  font-size: 13px;
}
</style>
