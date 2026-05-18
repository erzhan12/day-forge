<script setup lang="ts">
// Right-hand AI chat sidebar (feature 0008). Thin shell whose only
// responsibilities are positioning, the header/rail toggle UI, and
// emitting open/close changes. Persistence lives in the parent
// (Schedule.vue + chatSidebarStorage helper); thread state lives in
// `useChat` (module-level singleton), shared with the dock variant.

import type { TimeBlock, UndoAction } from "../types"
import CommandBar from "./CommandBar.vue"

defineProps<{
  date: string
  snapshotBlocks: () => TimeBlock[]
  pushUndo: (action: UndoAction) => void
}>()

const open = defineModel<boolean>("open", { required: true })

function toggle(): void {
  open.value = !open.value
}
</script>

<template>
  <aside
    class="chat-sidebar"
    :class="{ collapsed: !open }"
    data-testid="chat-sidebar"
    aria-label="AI chat"
  >
    <header v-if="open" class="chat-sidebar-header">
      <span class="chat-sidebar-title">AI Chat</span>
      <button
        type="button"
        class="chat-sidebar-toggle"
        data-testid="chat-sidebar-toggle"
        aria-label="Collapse AI chat panel"
        aria-controls="chat-sidebar-body"
        :aria-expanded="open"
        @click="toggle"
      >
        ›
      </button>
    </header>
    <div v-if="open" id="chat-sidebar-body" class="chat-sidebar-body">
      <CommandBar
        :date="date"
        :snapshot-blocks="snapshotBlocks"
        :push-undo="pushUndo"
        variant="sidebar"
      />
    </div>
    <button
      v-else
      type="button"
      class="chat-sidebar-toggle chat-sidebar-toggle-rail"
      data-testid="chat-sidebar-toggle"
      aria-label="Expand AI chat panel"
      aria-controls="chat-sidebar-body"
      :aria-expanded="open"
      @click="toggle"
    >
      ‹
    </button>
  </aside>
</template>

<style scoped>
.chat-sidebar {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 380px;
  background: var(--bg-panel);
  border-left: 1px solid var(--border);
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.05);
  z-index: 30;
  display: flex;
  flex-direction: column;
  transition: width 180ms ease;
  box-sizing: border-box;
}

.chat-sidebar.collapsed {
  width: 32px;
  align-items: center;
  justify-content: flex-start;
  padding-top: 8px;
}

.chat-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.chat-sidebar-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.chat-sidebar-toggle {
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

.chat-sidebar-toggle:hover {
  color: var(--text-primary);
  border-color: var(--text-faint);
}

.chat-sidebar-toggle:focus-visible {
  outline: 2px solid #3b82f6;
  outline-offset: 1px;
}

.chat-sidebar-toggle-rail {
  height: 32px;
}

.chat-sidebar-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
