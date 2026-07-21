<script setup lang="ts">
import type { Ref } from "vue"
import { computed, inject, ref } from "vue"
import type { TimeBlock, TravelRule, UndoAction } from "../types"
import type { NormalizedEvent } from "../types/calendar"
import { useSchedule } from "../composables/useSchedule"
import { computeEventBlockTimes } from "../utils/travelRules"
import {
  DAY_START,
  DAY_END,
  DAY_START_MINUTES,
  DAY_END_MINUTES,
  timeToMinutes,
} from "../utils/scheduleTime"

const MAX_TRAVEL_MINUTES = 600

const props = defineProps<{
  event: NormalizedEvent
  matchedRule: TravelRule | null
  date: string
  // The travel-rule fetch failed, so `matchedRule` is null because the rules
  // are UNKNOWN, not because none matched. Those two states produce identical
  // 0/0/"other" prefills, so the distinction has to be shown or the user
  // silently confirms an unpadded block believing their rule applied.
  rulesUnavailable?: boolean
}>()
const emit = defineEmits<{
  (e: "close"): void
}>()

// Function DateSource — the string variant would stale-capture the
// setup-time date if the user navigates dates while the dialog is open.
const { createBlockFromEvent } = useSchedule(() => props.date)

const undo = inject<{
  pushUndo: (action: UndoAction) => void
  snapshotBlocks: () => TimeBlock[]
} | null>("undo", null)

const scheduleDisabled = inject<Ref<boolean> | null>("scheduleDisabled", null)
const isDisabled = computed(() => Boolean(scheduleDisabled?.value))

// Prefill EVERY field from the matched rule (locked requirement); the bare
// 0/0/"other" values are the no-rule defaults only.
const travelThere = ref(props.matchedRule?.travel_there_minutes ?? 0)
const travelBack = ref(props.matchedRule?.travel_back_minutes ?? 0)
const category = ref<TimeBlock["category"]>(
  props.matchedRule?.category || "other",
)

const submitting = ref(false)
const errorMessage = ref("")

// Reject NaN / out-of-range before feeding computeEventBlockTimes so a
// wild override can't produce a nonsense preview.
function clampMinutes(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(MAX_TRAVEL_MINUTES, Math.round(value)))
}

const computedTimes = computed(() =>
  computeEventBlockTimes(
    props.event,
    props.date,
    clampMinutes(travelThere.value),
    clampMinutes(travelBack.value),
  ),
)

// null sentinel: event ± travel lies entirely outside the viewed local day
// (UTC-window artifact) — nothing sensible to create.
const outsideViewedDay = computed(() => computedTimes.value === null)

// Zero-length (e.g. DTEND-less CalDAV event with 0/0 travel): adding
// travel minutes stretches the range and re-enables Confirm.
const zeroLength = computed(() => {
  const t = computedTimes.value
  return t !== null && t.start_time === t.end_time
})

// The timeline renders only [06:00, 23:00) — warn (non-blocking) when the
// block would be created fine but never appear there.
const outsideVisibleHours = computed(() => {
  const t = computedTimes.value
  if (t === null || t.start_time === t.end_time) return false
  return (
    timeToMinutes(t.end_time) <= DAY_START_MINUTES ||
    timeToMinutes(t.start_time) >= DAY_END_MINUTES
  )
})

const confirmDisabled = computed(
  () =>
    submitting.value ||
    isDisabled.value ||
    outsideViewedDay.value ||
    zeroLength.value,
)

async function handleConfirm() {
  const times = computedTimes.value
  if (confirmDisabled.value || times === null) return
  submitting.value = true
  errorMessage.value = ""
  // Undo parity with AddBlockForm.handleSubmit: snapshot + date captured
  // BEFORE the request (issue #21 date-navigation guard).
  const snapshot = undo?.snapshotBlocks()
  const scheduleDate = props.date
  const blockTitle = props.event.title
  const result = await createBlockFromEvent({
    title: blockTitle,
    start_time: times.start_time,
    end_time: times.end_time,
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
    emit("close")
  } else {
    const errs = result.errors ?? {}
    errorMessage.value =
      Object.values(errs).flat().map(String).join(", ") ||
      "Failed to add block"
  }
}
</script>

<template>
  <div class="ats-backdrop" @click.self="emit('close')">
    <div
      class="ats-dialog"
      role="dialog"
      aria-modal="true"
      aria-label="Add event to schedule"
    >
      <header class="ats-header">
        <h3 class="ats-title">Add to schedule</h3>
        <button
          type="button"
          class="ats-close"
          aria-label="Close"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <p class="ats-event-title">{{ event.title }}</p>
      <p v-if="matchedRule" class="ats-rule-hint">
        Prefilled from rule “{{ matchedRule.keyword }}”
      </p>

      <div v-if="rulesUnavailable" class="ats-warning" data-testid="rules-unavailable">
        Travel rules couldn’t be loaded, so none were applied. Check the times
        below before adding.
      </div>
      <div v-if="errorMessage" class="ats-error">{{ errorMessage }}</div>

      <div class="ats-fields">
        <label class="ats-field">
          Travel there (min)
          <input
            v-model.number="travelThere"
            type="number"
            min="0"
            :max="MAX_TRAVEL_MINUTES"
            class="ats-input"
          />
        </label>
        <label class="ats-field">
          Travel back (min)
          <input
            v-model.number="travelBack"
            type="number"
            min="0"
            :max="MAX_TRAVEL_MINUTES"
            class="ats-input"
          />
        </label>
        <label class="ats-field">
          Category
          <select v-model="category" class="ats-input">
            <option value="work">Work</option>
            <option value="personal">Personal</option>
            <option value="health">Health</option>
            <option value="other">Other</option>
          </select>
        </label>
      </div>

      <!-- Read-only preview: title/times derive from the event. -->
      <p class="ats-preview">
        <template v-if="computedTimes">
          Block: <strong>{{ computedTimes.start_time }} –
          {{ computedTimes.end_time }}</strong>
        </template>
        <template v-else>—</template>
      </p>

      <p v-if="outsideViewedDay" class="ats-hint ats-hint--blocking">
        This event lies outside the viewed day.
      </p>
      <p v-else-if="zeroLength" class="ats-hint ats-hint--blocking">
        Zero-length event — add travel minutes to create a block.
      </p>
      <p v-else-if="outsideVisibleHours" class="ats-hint">
        This block falls outside the visible timeline hours {{ DAY_START }}–{{ DAY_END }}.
      </p>

      <div class="ats-actions">
        <button
          type="button"
          class="ats-confirm"
          :disabled="confirmDisabled"
          @click="handleConfirm"
        >
          {{ submitting ? "Adding…" : "Add block" }}
        </button>
        <button type="button" class="ats-cancel" @click="emit('close')">
          Cancel
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ats-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.ats-dialog {
  background: var(--bg-panel);
  border-radius: 10px;
  padding: 16px;
  width: min(360px, calc(100vw - 32px));
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
}

.ats-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.ats-title {
  margin: 0;
  font-size: 16px;
  color: var(--text-primary);
}

.ats-close {
  background: transparent;
  border: none;
  font-size: 20px;
  color: var(--text-muted);
  cursor: pointer;
  width: 28px;
  height: 28px;
  border-radius: 6px;
}

.ats-close:hover {
  background: var(--bg-schedule-gap);
}

.ats-event-title {
  margin: 0;
  font-weight: 500;
  color: var(--text-primary);
}

.ats-rule-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.ats-error {
  background: var(--danger-surface);
  color: var(--danger-text);
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
}

.ats-warning {
  background: var(--warning-surface);
  color: var(--warning-text);
  border: 1px solid var(--warning-border);
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
}

.ats-fields {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.ats-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

.ats-input {
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 14px;
  width: 110px;
  background: var(--bg-page);
  color: var(--text-primary);
}

.ats-preview {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary);
}

.ats-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.ats-hint--blocking {
  color: var(--danger-text);
}

.ats-actions {
  display: flex;
  gap: 8px;
}

.ats-confirm {
  padding: 8px 20px;
  background: var(--accent);
  color: var(--accent-contrast);
  border: none;
  border-radius: 6px;
  font-weight: 500;
  cursor: pointer;
}

.ats-confirm:hover:not(:disabled) {
  background: var(--accent-hover);
}

.ats-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.ats-cancel {
  padding: 8px 20px;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  color: var(--text-muted);
  cursor: pointer;
}
</style>
