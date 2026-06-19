<script setup lang="ts">
import type { TodoistTask } from "../types/todoist"

defineProps<{
  tasks: TodoistTask[]
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{ (e: "retry"): void }>()
</script>

<template>
  <div class="todoist-panel" data-testid="todoist-panel">
    <span v-if="loading" class="todoist-loading" aria-live="polite">Loading…</span>

    <div v-if="error" class="todoist-error" role="status">
      <span>{{ error }}</span>
      <button type="button" class="todoist-retry" @click="emit('retry')">Retry</button>
    </div>

    <ul v-else-if="!loading && tasks.length > 0" class="todoist-list">
      <li
        v-for="task in tasks"
        :key="task.id"
        class="todoist-item"
        data-testid="todoist-task"
      >
        <span
          class="todoist-priority-dot"
          :class="`todoist-priority-${task.ui_priority}`"
          :title="task.ui_priority"
          aria-hidden="true"
        ></span>
        <span class="todoist-task-title">{{ task.title }}</span>
      </li>
    </ul>

    <p v-else-if="loading" class="todoist-skeleton" aria-hidden="true">
      <span class="todoist-skel-row"></span>
      <span class="todoist-skel-row"></span>
      <span class="todoist-skel-row"></span>
      <span class="todoist-skel-row"></span>
    </p>

    <p v-else class="todoist-empty">No tasks scheduled for this day.</p>
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

.todoist-priority-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  flex-shrink: 0;
}

.todoist-priority-P1 {
  background: var(--danger-text);
}

.todoist-priority-P2 {
  background: var(--warning-text, #d9822b);
}

.todoist-priority-P3 {
  background: var(--accent, #3b82f6);
}

.todoist-priority-P4 {
  background: var(--text-muted);
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
</style>
