<script setup lang="ts">
import type {
  GoogleAccountError,
  NormalizedEvent,
  ProviderErrorBanner,
} from "../types/calendar"

withDefaults(
  defineProps<{
    events: NormalizedEvent[]
    loading: boolean
    connected: boolean
    // Whole-request provider failures (Apple 502/504, Google 401/502/504).
    // Rendered as NON-suppressing banners above the list — a single
    // provider's failure must not blank the other provider's healthy events.
    errorBanners?: ProviderErrorBanner[]
    // Per-account Google failures (200 + account_errors[]).
    accountErrors?: GoogleAccountError[]
  }>(),
  {
    errorBanners: () => [],
    accountErrors: () => [],
  },
)

const emit = defineEmits<{ (e: "retry", provider: "apple" | "google"): void }>()

// Compose-time format: ISO8601 → HH:MM in viewer's local TZ. All-day
// events show a flat "All day" badge instead of a time range.
function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
}
</script>

<template>
  <!-- When not connected, render nothing (V1 simplification per the plan). -->
  <section v-if="connected" class="external-events" aria-label="External calendar events">
    <header class="ee-header">
      <span class="ee-title">External Calendars</span>
      <span v-if="loading" class="ee-loading" aria-live="polite">Loading…</span>
    </header>

    <!-- Whole-request provider failures. NON-suppressing: each renders as a
         banner above the list and carries its own per-provider Retry. -->
    <div
      v-for="banner in errorBanners"
      :key="`err-${banner.provider}`"
      class="ee-error"
      role="status"
      data-testid="provider-error"
    >
      <span>{{ banner.message }}</span>
      <button
        type="button"
        class="ee-retry"
        @click="emit('retry', banner.provider)"
      >
        Retry
      </button>
    </div>

    <!-- Per-account (Google) failures. Also non-suppressing — working
         accounts' events still render below. -->
    <div
      v-for="acctErr in accountErrors"
      :key="`acct-${acctErr.account_id}`"
      class="ee-account-error"
      role="status"
      data-testid="account-error"
    >
      <template v-if="acctErr.error === 'reconnect_required'">
        <span>{{ acctErr.email }} needs reconnecting.</span>
        <a class="ee-reconnect" href="/settings/">Reconnect</a>
      </template>
      <template v-else>
        <span>{{ acctErr.email }} is temporarily unavailable.</span>
      </template>
    </div>

    <!-- Event list renders whenever there are events, regardless of banners. -->
    <ul v-if="events.length > 0" class="ee-list">
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
        <div class="ee-chips">
          <span class="ee-calendar-chip">{{ ev.calendar_name }}</span>
          <span v-if="ev.account_label" class="ee-account-chip">{{ ev.account_label }}</span>
        </div>
      </li>
    </ul>

    <!-- Full-bleed empty / skeleton state ONLY when there are no events. -->
    <template v-else>
      <p v-if="loading" class="ee-skeleton" aria-hidden="true">
        <span class="ee-skel-row"></span>
        <span class="ee-skel-row"></span>
        <span class="ee-skel-row"></span>
        <span class="ee-skel-row"></span>
      </p>
      <p
        v-else-if="errorBanners.length === 0 && accountErrors.length === 0"
        class="ee-empty"
      >
        No external calendar events for this day.
      </p>
    </template>
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

/* Both chips share the SINGLE `auto` grid cell so a second chip doesn't
   become a 4th grid item and wrap onto an implicit row. Flex + wrap lets the
   two chips stack cleanly under each other on narrow widths. */
.ee-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
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

.ee-account-chip {
  font-size: 10px;
  letter-spacing: 0.02em;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--border-strong);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}

.ee-account-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
  font-size: 12px;
}

.ee-reconnect {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--danger-border);
  border-radius: 4px;
  color: var(--danger-text);
  text-decoration: none;
  white-space: nowrap;
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
