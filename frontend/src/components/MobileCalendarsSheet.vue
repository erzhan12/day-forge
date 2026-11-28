<script setup lang="ts">
// "Calendars" opened from the mobile gear menu (feature 0113, SPEC 11.8 item
// 2): the existing calendar panel in a modal sheet. The owner passes the panel
// as the default slot so its props and Add to schedule wiring stay in
// Schedule.vue.
import { ref } from "vue"
import { useMobileDialog } from "../composables/useMobileDialog"

const props = defineProps<{ fallbackFocus?: () => HTMLElement | null }>()
const emit = defineEmits<{ close: [] }>()

const sheet = ref<HTMLElement | null>(null)
useMobileDialog(sheet, { onClose: () => emit("close"), fallbackFocus: props.fallbackFocus })
</script>

<template>
  <div class="calendars-backdrop" data-testid="mobile-calendars-backdrop" @click.self="emit('close')">
    <section
      ref="sheet"
      class="calendars-sheet"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mobile-calendars-title"
      data-testid="mobile-calendars"
    >
      <header class="sheet-head">
        <h2 id="mobile-calendars-title">Calendars</h2>
        <button type="button" class="df-btn df-btn--secondary" data-testid="mobile-calendars-close" @click="emit('close')">Close</button>
      </header>
      <div class="sheet-body"><slot /></div>
    </section>
  </div>
</template>

<style scoped>
html[data-theme="dark_4a"] .calendars-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: flex-end;
  background: rgba(0, 0, 0, 0.55);
}

html[data-theme="dark_4a"] .calendars-sheet {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-height: 80dvh;
  padding-bottom: var(--safe-bottom);
  background: #1f2023;
  border-top: 1px solid #6a6e75;
  border-radius: 16px 16px 0 0;
}

html[data-theme="dark_4a"] .sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #34363b;
}

html[data-theme="dark_4a"] .sheet-head h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #e5e7eb;
}

html[data-theme="dark_4a"] .sheet-body {
  overflow-y: auto;
  padding: 12px 16px 16px;
}
</style>
