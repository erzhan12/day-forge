<script setup lang="ts">
// Add Block FAB of the Dark 4a phone layout (feature 0113, SPEC 11.4): 56 px
// coral circle, 16 px from the right and 16 px above the chat panel. It hides
// while the chat field has focus so it never covers chips, field or keyboard.
defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ click: [] }>()
</script>

<template>
  <button
    type="button"
    class="mobile-fab"
    aria-label="Add block"
    :disabled="disabled"
    data-testid="mobile-fab"
    @click="emit('click')"
  >
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M12 4v16M4 12h16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" /></svg>
  </button>
</template>

<style scoped>
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .mobile-fab {
    position: fixed;
    right: 16px;
    bottom: calc(var(--chat-dock-height, calc(52px + var(--safe-bottom))) + 16px);
    z-index: 30;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: #fd7562;
    color: #17181a;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45), 0 1px 3px rgba(0, 0, 0, 0.3);
  }

  html[data-theme="dark_4a"] .mobile-fab:disabled {
    opacity: 0.5;
  }

  html[data-theme="dark_4a"] .mobile-fab:focus-visible {
    outline: 2px solid #e5e7eb;
    outline-offset: 2px;
  }

  html[data-theme="dark_4a"] .schedule-page:has(.command-input:focus) .mobile-fab {
    display: none;
  }
}
</style>
