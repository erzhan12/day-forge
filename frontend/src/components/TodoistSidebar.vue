<script setup lang="ts">
// Left-hand Todoist task sidebar (feature 0020). Mirrors ChatSidebar.vue on
// the opposite edge: fixed viewport frame, header + rail toggle. Persistence
// lives in Schedule.vue + todoistSidebarStorage; task data in useTodoist.

import type { TodoistTask } from "../types/todoist"
import TodoistTasksPanel from "./TodoistTasksPanel.vue"

defineProps<{
  tasks: TodoistTask[]
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{ (e: "retry"): void }>()

const open = defineModel<boolean>("open", { required: true })

function toggle(): void {
  open.value = !open.value
}
</script>

<template>
  <aside
    class="todoist-sidebar"
    :class="{ collapsed: !open }"
    data-testid="todoist-sidebar"
    aria-label="Todoist tasks"
  >
    <header v-if="open" class="todoist-sidebar-header">
      <span class="todoist-sidebar-title">Todoist</span>
      <button
        type="button"
        class="todoist-sidebar-toggle"
        data-testid="todoist-sidebar-toggle"
        aria-label="Collapse Todoist panel"
        aria-controls="todoist-sidebar-body"
        :aria-expanded="open"
        @click="toggle"
      >
        ‹
      </button>
    </header>
    <div v-if="open" id="todoist-sidebar-body" class="todoist-sidebar-body">
      <TodoistTasksPanel
        :tasks="tasks"
        :loading="loading"
        :error="error"
        @retry="emit('retry')"
      />
    </div>
    <button
      v-else
      type="button"
      class="todoist-sidebar-toggle todoist-sidebar-toggle-rail"
      data-testid="todoist-sidebar-toggle"
      aria-label="Expand Todoist panel"
      aria-controls="todoist-sidebar-body"
      :aria-expanded="open"
      @click="toggle"
    >
      ›
    </button>
  </aside>
</template>

<style scoped>
.todoist-sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: 380px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.05);
  z-index: 30;
  display: flex;
  flex-direction: column;
  transition: width 180ms ease;
  box-sizing: border-box;
  overflow: hidden;
}

.todoist-sidebar.collapsed {
  width: 32px;
  align-items: center;
  justify-content: flex-start;
  padding-top: 8px;
}

.todoist-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.todoist-sidebar-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.todoist-sidebar-toggle {
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  color: var(--text-muted);
  cursor: pointer;
  width: 32px;
  height: 32px;
  font-size: 16px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.todoist-sidebar-toggle:hover {
  color: var(--text-primary);
  border-color: var(--text-faint);
}

.todoist-sidebar-toggle:focus-visible {
  outline: 2px solid #3b82f6;
  outline-offset: 1px;
}

.todoist-sidebar-toggle-rail {
  height: 32px;
}

.todoist-sidebar-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
