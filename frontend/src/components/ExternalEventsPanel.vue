<script setup lang="ts">
import type { NormalizedEvent } from "../types/calendar"

defineProps<{
  events: NormalizedEvent[]
  loading: boolean
  error: string | null
  connected: boolean
}>()

const emit = defineEmits<{ (e: "retry"): void }>()

// Compose-time format: ISO8601 → HH:MM in viewer's local TZ. All-day
// events show a flat "All day" badge instead of a time range.
function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
}
</script>

<template>
  <!-- When not connected, render nothing (V1 simplification per the plan). -->
  <section v-if="connected" class="external-events" aria-label="Apple Calendar events">
    <header class="ee-header">
      <span class="ee-title">Apple Calendar</span>
      <span v-if="loading" class="ee-loading" aria-live="polite">Loading…</span>
    </header>

    <div v-if="error" class="ee-error" role="status">
      <span>{{ error }}</span>
      <button type="button" class="ee-retry" @click="emit('retry')">Retry</button>
    </div>

    <ul v-else-if="!loading && events.length > 0" class="ee-list">
      <li
        v-for="ev in events"
        :key="ev.external_uid"
        class="ee-item"
        data-testid="external-event"
      >
        <span class="ee-time">
          <template v-if="ev.all_day">All day</template>
          <template v-else>{{ formatTime(ev.start) }} – {{ formatTime(ev.end) }}</template>
        </span>
        <span class="ee-event-title">{{ ev.title }}</span>
        <span class="ee-calendar-chip">{{ ev.calendar_name }}</span>
      </li>
    </ul>

    <p v-else-if="loading" class="ee-skeleton" aria-hidden="true">
      <span class="ee-skel-row"></span>
      <span class="ee-skel-row"></span>
    </p>

    <p v-else class="ee-empty">No Apple Calendar events for this day.</p>
  </section>
</template>

<style scoped>
.external-events {
  margin: 12px 16px;
  padding: 12px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
}

.ee-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 500;
  color: var(--text-secondary);
}

.ee-title {
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 11px;
}

.ee-loading {
  font-size: 11px;
  color: var(--text-muted);
}

.ee-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
}

.ee-retry {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--danger-border);
  border-radius: 4px;
  background: transparent;
  color: var(--danger-text);
  cursor: pointer;
}

.ee-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ee-item {
  display: grid;
  grid-template-columns: 100px 1fr auto;
  gap: 8px;
  align-items: center;
  padding: 4px 0;
  color: var(--text-primary);
}

.ee-time {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--text-secondary);
}

.ee-event-title {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ee-calendar-chip {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--bg-schedule-gap);
  color: var(--text-muted);
}

.ee-empty {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.ee-skeleton {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ee-skel-row {
  height: 16px;
  background: var(--bg-schedule-gap);
  border-radius: 4px;
  opacity: 0.6;
}
</style>
