<script setup lang="ts">
// Gear menu of the Dark 4a mobile header (feature 0113, SPEC 11.2). A modal
// panel under the header: Settings, View analytics, Calendars, Log out.
import { ref } from "vue"
import { Link } from "@inertiajs/vue3"
import { useMobileDialog } from "../composables/useMobileDialog"
import { useBodyScrollLock } from "../composables/useBodyScrollLock"

const props = defineProps<{
  date: string
  showAnalytics: boolean
  showCalendars: boolean
}>()

const emit = defineEmits<{ close: []; calendars: []; logout: [] }>()

const panel = ref<HTMLElement | null>(null)
useBodyScrollLock()
useMobileDialog(panel, { onClose: () => emit("close") })
</script>

<template>
  <div class="mobile-menu-backdrop" data-testid="mobile-menu-backdrop" @click.self="emit('close')">
    <div
      ref="panel"
      class="mobile-menu"
      role="dialog"
      aria-modal="true"
      aria-label="Menu"
      data-testid="mobile-menu"
    >
      <Link href="/settings/" class="menu-item" data-testid="mobile-menu-settings">Settings</Link>
      <Link
        v-if="props.showAnalytics"
        :href="`/analytics/${props.date}/`"
        class="menu-item"
        data-testid="mobile-menu-analytics"
      >View analytics</Link>
      <button
        v-if="props.showCalendars"
        type="button"
        class="menu-item"
        data-testid="mobile-menu-calendars"
        @click="emit('calendars')"
      >Calendars</button>
      <div class="menu-footer">
        <button
          type="button"
          class="df-btn df-btn--secondary menu-logout"
          data-testid="mobile-menu-logout"
          @click="emit('logout')"
        >Log out</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
html[data-theme="dark_4a"] .mobile-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(0, 0, 0, 0.45);
}

html[data-theme="dark_4a"] .mobile-menu {
  position: absolute;
  top: calc(var(--safe-top) + 56px);
  right: 8px;
  width: min(260px, calc(100vw - 16px));
  padding: 4px 0;
  background: #1f2023;
  border: 1px solid #6a6e75;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}

html[data-theme="dark_4a"] .menu-item {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 44px;
  padding: 0 16px;
  border: 0;
  background: transparent;
  color: #e5e7eb;
  font: inherit;
  font-size: 16px;
  text-align: left;
  text-decoration: none;
}

html[data-theme="dark_4a"] .menu-item:focus-visible {
  outline: 2px solid #fd7562;
  outline-offset: -2px;
}

html[data-theme="dark_4a"] .menu-footer {
  margin-top: 4px;
  padding: 8px 12px 8px;
  border-top: 1px solid #34363b;
}

html[data-theme="dark_4a"] .menu-logout {
  width: 100%;
  min-height: 44px;
}
</style>
