<script setup lang="ts">
// Left-hand Todoist task sidebar (feature 0020). Mirrors ChatSidebar.vue on
// the opposite edge: fixed viewport frame, header + rail toggle. Persistence
// lives in Schedule.vue + todoistSidebarStorage; task data in useTodoist.

import type { TodoistTask } from "../types/todoist"
import TodoistTasksPanel from "./TodoistTasksPanel.vue"

// The left sidebar hosts both the Todoist task list AND (via the default slot,
// feature 0022) the external-calendar panel stacked below it. Either section
// shows independently: `showTasks` when Todoist is connected, `showExtra` when
// a calendar is connected. Schedule.vue gates the whole sidebar on
// `showTasks || showExtra`.
withDefaults(
  defineProps<{
    tasks: TodoistTask[]
    loading: boolean
    error: string | null
    showTasks?: boolean
    showExtra?: boolean
  }>(),
  { showTasks: true, showExtra: false },
)

const emit = defineEmits<{
  (e: "retry"): void
  (e: "complete", taskId: string): void
  (e: "refresh"): void
}>()

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
    :aria-label="showTasks ? 'Todoist tasks' : 'Calendar'"
  >
    <header v-if="open" class="todoist-sidebar-header">
      <span class="todoist-sidebar-title">{{ showTasks ? "Todoist" : "Calendar" }}</span>
      <div class="todoist-sidebar-actions">
        <button
          v-if="showTasks"
          type="button"
          class="todoist-sidebar-toggle"
          data-testid="todoist-sidebar-refresh"
          aria-label="Refresh Todoist tasks"
          @click="emit('refresh')"
        >
          ⟳
        </button>
        <button
          type="button"
          class="todoist-sidebar-toggle"
          data-testid="todoist-sidebar-toggle"
          :aria-label="showTasks ? 'Collapse Todoist panel' : 'Collapse Calendar panel'"
          aria-controls="todoist-sidebar-body"
          :aria-expanded="open"
          @click="toggle"
        >
          ‹
        </button>
      </div>
    </header>
    <div v-if="open" id="todoist-sidebar-body" class="todoist-sidebar-body">
      <TodoistTasksPanel
        v-if="showTasks"
        class="todoist-sidebar-tasks"
        :tasks="tasks"
        :loading="loading"
        :error="error"
        @retry="emit('retry')"
        @complete="emit('complete', $event)"
      />
      <!-- External-calendar panel (feature 0022), stacked below the tasks. -->
      <div v-if="showExtra" class="todoist-sidebar-extra">
        <slot />
      </div>
    </div>
    <button
      v-else
      type="button"
      class="todoist-sidebar-toggle todoist-sidebar-toggle-rail"
      data-testid="todoist-sidebar-toggle"
      :aria-label="showTasks ? 'Expand Todoist panel' : 'Expand Calendar panel'"
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

/* Keep the header layout `title | [refresh][collapse]` — wrapping the two
   buttons in a flex group stops `justify-content: space-between` from
   spreading three children apart. */
.todoist-sidebar-actions {
  display: flex;
  gap: 4px;
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

/* Task list takes the growing space and keeps its own internal scroll. */
.todoist-sidebar-tasks {
  flex: 1 1 auto;
  min-height: 0;
}

/* Calendar panel sits below with a capped height + its own scroll, so a long
   event list never pushes the task list off-screen. When Todoist isn't
   connected (`showTasks` false) it's the only child and simply sizes to
   content at the top. */
.todoist-sidebar-extra {
  flex: 0 0 auto;
  max-height: 50%;
  overflow-y: auto;
  border-top: 1px solid var(--border);
}
</style>
