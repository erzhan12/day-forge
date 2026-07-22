<script setup lang="ts">
import { computed } from "vue"
import type { HabiticaTask } from "../types/habitica"
import type { TodoistTask } from "../types/todoist"
import HabiticaTasksSection from "./HabiticaTasksSection.vue"
import TodoistTasksPanel from "./TodoistTasksPanel.vue"

const props = withDefaults(
  defineProps<{
    todoistTasks: TodoistTask[]
    todoistLoading: boolean
    todoistError: string | null
    showTodoist?: boolean
    habiticaTasks: HabiticaTask[]
    habiticaLoading: boolean
    habiticaError: string | null
    showHabitica?: boolean
    showExtra?: boolean
  }>(),
  { showTodoist: false, showHabitica: false, showExtra: false },
)

const showAnyTasks = computed(() => props.showTodoist || props.showHabitica)
const panelTitle = computed(() =>
  showAnyTasks.value && props.showExtra
    ? "Tasks & Calendar"
    : showAnyTasks.value
      ? "Tasks"
      : "Calendar",
)
const panelNoun = computed(() =>
  showAnyTasks.value && props.showExtra
    ? "Tasks and Calendar"
    : showAnyTasks.value
      ? "External tasks"
      : "Calendar",
)

const emit = defineEmits<{
  (e: "todoistRetry"): void
  (e: "todoistComplete", taskId: string): void
  (e: "habiticaRetry"): void
  (e: "habiticaComplete", taskId: string): void
  (e: "refresh"): void
}>()

const open = defineModel<boolean>("open", { required: true })

function toggle(): void {
  open.value = !open.value
}
</script>

<template>
  <!-- The `todoist-sidebar*` data-testids are deliberately NOT renamed to
       match this component: frontend/scripts/playwright/*.mjs still selects
       on them. They are Playwright's contract, not dead naming from the
       TodoistSidebar → ExternalTasksSidebar rename. Same reasoning as the
       localStorage key in externalTasksSidebarStorage.ts. -->
  <aside
    class="external-tasks-sidebar"
    :class="{ collapsed: !open }"
    data-testid="todoist-sidebar"
    :aria-label="panelNoun"
  >
    <header v-if="open" class="external-tasks-sidebar-header">
      <span class="external-tasks-sidebar-title">{{ panelTitle }}</span>
      <div class="external-tasks-sidebar-actions">
        <button
          v-if="showAnyTasks"
          type="button"
          class="external-tasks-sidebar-toggle"
          data-testid="todoist-sidebar-refresh"
          aria-label="Refresh external tasks"
          @click="emit('refresh')"
        >
          ⟳
        </button>
        <button
          type="button"
          class="external-tasks-sidebar-toggle"
          data-testid="todoist-sidebar-toggle"
          :aria-label="`Collapse ${panelTitle} panel`"
          aria-controls="external-tasks-sidebar-body"
          :aria-expanded="open"
          @click="toggle"
        >
          ‹
        </button>
      </div>
    </header>

    <div
      v-if="open"
      id="external-tasks-sidebar-body"
      class="external-tasks-sidebar-body"
    >
      <section v-if="showTodoist" class="external-tasks-section">
        <header class="external-tasks-section-header">
          <span>Todoist</span>
          <span>{{ todoistTasks.length }}</span>
        </header>
        <TodoistTasksPanel
          class="external-tasks-section-body"
          :tasks="todoistTasks"
          :loading="todoistLoading"
          :error="todoistError"
          @retry="emit('todoistRetry')"
          @complete="emit('todoistComplete', $event)"
        />
      </section>

      <section v-if="showHabitica" class="external-tasks-section">
        <header class="external-tasks-section-header">
          <span>Habitica</span>
          <span>{{ habiticaTasks.length }}</span>
        </header>
        <HabiticaTasksSection
          class="external-tasks-section-body"
          :tasks="habiticaTasks"
          :loading="habiticaLoading"
          :error="habiticaError"
          @retry="emit('habiticaRetry')"
          @complete="emit('habiticaComplete', $event)"
        />
      </section>

      <div v-if="showExtra" class="external-tasks-sidebar-extra">
        <slot />
      </div>
    </div>

    <button
      v-else
      type="button"
      class="external-tasks-sidebar-toggle external-tasks-sidebar-toggle-rail"
      data-testid="todoist-sidebar-toggle"
      :aria-label="`Expand ${panelTitle} panel`"
      aria-controls="external-tasks-sidebar-body"
      :aria-expanded="open"
      @click="toggle"
    >
      ›
    </button>
  </aside>
</template>

<style scoped>
.external-tasks-sidebar {
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

.external-tasks-sidebar.collapsed {
  width: 32px;
  align-items: center;
  justify-content: flex-start;
  padding-top: 8px;
}

.external-tasks-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.external-tasks-sidebar-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  /* Dropped when .todoist-sidebar-title was renamed in Phase 0; restored so
     the heading keeps the tracking every other sidebar title uses. */
  letter-spacing: 0.02em;
}

.external-tasks-sidebar-actions {
  display: flex;
  gap: 4px;
}

.external-tasks-sidebar-toggle {
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

.external-tasks-sidebar-toggle:hover {
  color: var(--text-primary);
  border-color: var(--text-faint);
}

.external-tasks-sidebar-toggle:focus-visible {
  outline: 2px solid #3b82f6;
  outline-offset: 1px;
}

.external-tasks-sidebar-toggle-rail {
  height: 32px;
}

.external-tasks-sidebar-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.external-tasks-section {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-bottom: 1px solid var(--border);
}

.external-tasks-section-header {
  flex: 0 0 auto;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.external-tasks-section-body {
  flex: 1 1 auto;
  min-height: 0;
}

.external-tasks-sidebar-extra {
  flex: 0 0 auto;
  max-height: 50%;
  overflow-y: auto;
  border-top: 1px solid var(--border);
}
</style>
