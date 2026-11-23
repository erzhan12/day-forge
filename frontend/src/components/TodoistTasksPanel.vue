<script setup lang="ts">
import type { TodoistTask } from "../types/todoist"
import { lockLeavingTaskRow } from "../utils/taskRowLeave"

defineProps<{
  tasks: TodoistTask[]
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  (e: "retry"): void
  (e: "complete", taskId: string): void
}>()
</script>

<template>
  <div class="todoist-panel" data-testid="todoist-panel">
    <span v-if="loading" class="todoist-loading" aria-live="polite">Loading…</span>

    <div v-if="error" class="todoist-error" role="status">
      <span>{{ error }}</span>
      <button type="button" class="todoist-retry" @click="emit('retry')">Retry</button>
    </div>

    <!-- Always mounted so the last completed row can still play its leave
         animation; `.todoist-list:empty` hides it once nothing is left. -->
    <TransitionGroup tag="ul" name="df-task" class="todoist-list" @before-leave="lockLeavingTaskRow">
      <li
        v-for="task in tasks"
        :key="task.id"
        class="todoist-item"
        data-testid="todoist-task"
      >
        <input
          type="checkbox"
          class="todoist-complete df-checkbox"
          data-testid="todoist-complete"
          :aria-label="`Complete task: ${task.title}`"
          @change="emit('complete', task.id)"
        />
        <span class="todoist-task-title df-task-title">{{ task.title }}</span>
      </li>
    </TransitionGroup>

    <!-- Standalone v-ifs restate the exclusions the old v-else-if chain gave
         them implicitly: never both, and never the empty copy mid-load. -->
    <p v-if="tasks.length === 0 && loading && !error" class="todoist-skeleton" aria-hidden="true">
      <span class="todoist-skel-row"></span>
      <span class="todoist-skel-row"></span>
      <span class="todoist-skel-row"></span>
      <span class="todoist-skel-row"></span>
    </p>

    <p v-if="tasks.length === 0 && !loading && !error" class="todoist-empty">No tasks scheduled for this day.</p>
  </div>
</template>

<style scoped>
.todoist-panel {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  font-size: 13px;
  overflow: hidden;
}

.todoist-loading {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.todoist-error {
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

.todoist-retry {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--danger-border);
  border-radius: 4px;
  background: transparent;
  color: var(--danger-text);
  cursor: pointer;
}

.todoist-list {
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

.todoist-item {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 8px;
  align-items: center;
  padding: 4px 0;
  color: var(--text-primary);
  flex-shrink: 0;
}

.todoist-list:empty {
  display: none;
}

.todoist-complete {
  --checkbox-color: var(--provider-todoist);
  --checkbox-tick: var(--provider-todoist-tick);
}

.todoist-task-title {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.todoist-empty {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.todoist-skeleton {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.todoist-skel-row {
  height: 16px;
  background: var(--bg-schedule-gap);
  border-radius: 4px;
  opacity: 0.6;
  flex-shrink: 0;
}

/* Dark 4a text floor (feature 0106): nothing below 13 px. */
html[data-theme="dark_4a"] .todoist-loading,
html[data-theme="dark_4a"] .todoist-retry,
html[data-theme="dark_4a"] .todoist-empty {
  font-size: 13px;
}
</style>
