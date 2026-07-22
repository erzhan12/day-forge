<script setup lang="ts">
import type { HabiticaTask } from "../types/habitica"

defineProps<{
  tasks: HabiticaTask[]
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  (e: "retry"): void
  (e: "complete", taskId: string): void
}>()
</script>

<template>
  <div class="habitica-panel" data-testid="habitica-panel">
    <!-- Only while rows are already on screen (background refresh). With an
         empty list the skeleton below covers the loading state, and rendering
         both produced "Loading…" stacked on top of three skeleton rows. -->
    <span
      v-if="loading && tasks.length > 0"
      class="habitica-loading"
      aria-live="polite"
      >Loading…</span
    >

    <div v-if="error" class="habitica-error" role="status">
      <span>{{ error }}</span>
      <button type="button" class="habitica-retry" @click="emit('retry')">
        Retry
      </button>
    </div>

    <ul v-else-if="!loading && tasks.length > 0" class="habitica-list">
      <li
        v-for="task in tasks"
        :key="task.id"
        class="habitica-item"
        data-testid="habitica-task"
      >
        <input
          type="checkbox"
          class="habitica-complete"
          data-testid="habitica-complete"
          :aria-label="`Complete Habitica task: ${task.title}`"
          @change="emit('complete', task.id)"
        />
        <span class="habitica-type" :class="`habitica-type-${task.type}`">
          {{ task.type === "daily" ? "Daily" : "Todo" }}
        </span>
        <span class="habitica-task-title">{{ task.title }}</span>
      </li>
    </ul>

    <!-- The rows are decorative, but the state still needs announcing: the
         visible "Loading…" text is suppressed in this branch, so the label
         lives here instead. -->
    <p
      v-else-if="loading"
      class="habitica-skeleton"
      role="status"
      aria-label="Loading Habitica tasks"
    >
      <span class="habitica-skel-row" aria-hidden="true"></span>
      <span class="habitica-skel-row" aria-hidden="true"></span>
      <span class="habitica-skel-row" aria-hidden="true"></span>
    </p>

    <p v-else class="habitica-empty">No Habitica tasks for this day.</p>
  </div>
</template>

<style scoped>
.habitica-panel {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  font-size: 13px;
  overflow: hidden;
}

.habitica-loading,
.habitica-empty {
  font-size: 12px;
  color: var(--text-muted);
}

.habitica-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
  flex-shrink: 0;
}

.habitica-retry {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--danger-border);
  border-radius: 4px;
  background: transparent;
  color: var(--danger-text);
  cursor: pointer;
}

.habitica-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.habitica-item {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 8px;
  align-items: center;
  padding: 4px 0;
  color: var(--text-primary);
  flex-shrink: 0;
}

.habitica-complete {
  width: 14px;
  height: 14px;
  margin: 0;
  cursor: pointer;
}

.habitica-type {
  min-width: 42px;
  font-size: 10px;
  line-height: 1;
  padding: 3px 5px;
  border-radius: 4px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-schedule-gap);
}

.habitica-type-daily {
  color: var(--accent, #3b82f6);
}

.habitica-task-title {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.habitica-skeleton {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.habitica-skel-row {
  height: 16px;
  background: var(--bg-schedule-gap);
  border-radius: 4px;
  opacity: 0.6;
}
</style>
