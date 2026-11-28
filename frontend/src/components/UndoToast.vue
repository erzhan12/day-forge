<script setup lang="ts">
withDefaults(
  defineProps<{
    message: string
    actionable?: boolean
    /** Dark 4a phone (feature 0113): tokens, 44px Undo, no close, above the FAB. */
    mobile?: boolean
  }>(),
  { actionable: true },
)

const emit = defineEmits<{
  undo: []
  dismiss: []
}>()
</script>

<template>
  <Transition name="toast">
    <div class="undo-toast" :class="{ 'undo-toast--mobile': mobile }" data-testid="undo-toast">
      <span class="toast-message">{{ message }}</span>
      <button v-if="actionable !== false" class="toast-undo-btn" @click="emit('undo')">Undo</button>
      <button v-if="!mobile" class="toast-close-btn" @click="emit('dismiss')">&times;</button>
      <div class="toast-progress" />
    </div>
  </Transition>
</template>

<style scoped>
.undo-toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 1000;
  background: #1f2937;
  color: white;
  border-radius: 10px;
  padding: 12px 16px;
  min-width: 280px;
  max-width: 400px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  display: flex;
  align-items: center;
  gap: 12px;
  overflow: hidden;
}

.toast-message {
  flex: 1;
  font-size: 14px;
  line-height: 1.4;
}

.toast-undo-btn {
  background: none;
  border: none;
  color: #60a5fa;
  font-size: 14px;
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
  padding: 2px 4px;
  flex-shrink: 0;
}

.toast-undo-btn:hover {
  color: #93bbfd;
}

.toast-close-btn {
  background: none;
  border: none;
  color: var(--text-faint);
  font-size: 18px;
  cursor: pointer;
  padding: 2px 4px;
  line-height: 1;
  flex-shrink: 0;
}

.toast-close-btn:hover {
  color: white;
}

.toast-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 3px;
  background: var(--accent);
  animation: shrink var(--toast-duration, 8s) linear forwards;
}

@keyframes shrink {
  from {
    width: 100%;
  }
  to {
    width: 0%;
  }
}

/* Transition classes */
.toast-enter-active {
  transition: all 200ms ease-out;
}

.toast-leave-active {
  transition: all 150ms ease-in;
}

.toast-enter-from {
  opacity: 0;
  transform: translateY(16px);
}

.toast-leave-to {
  opacity: 0;
}

/* Dark 4a phone (feature 0113, SPEC 11): sits above the FAB, or above the
 * chat dock when the FAB is hidden, and is shifted left of the 56px button. */
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .undo-toast.undo-toast--mobile {
    --toast-duration: 5s;
    left: 16px;
    right: calc(16px + 56px + 16px);
    bottom: calc(var(--chat-dock-height, calc(52px + var(--safe-bottom))) + 16px + 56px + 16px);
    min-width: 0;
    max-width: none;
    min-height: 44px;
    padding: 0 16px;
    background: #1F2023;
    color: #E5E7EB;
    border: 1px solid #6A6E75;
    box-shadow: none;
  }

  html[data-theme="dark_4a"] .undo-toast.undo-toast--mobile .toast-message {
    font-size: 14px;
    font-weight: 500;
    color: #E5E7EB;
  }

  html[data-theme="dark_4a"] .undo-toast.undo-toast--mobile .toast-undo-btn {
    color: #FD7562;
    font-weight: 500;
    text-decoration: none;
    min-height: 44px;
    min-width: 44px;
    padding: 0 8px;
  }

  html[data-theme="dark_4a"] .undo-toast.undo-toast--mobile .toast-undo-btn:hover {
    color: #FD7562;
  }

  html[data-theme="dark_4a"] .schedule-page:has(.command-input:focus) .undo-toast.undo-toast--mobile {
    right: 16px;
    bottom: calc(var(--chat-dock-height, calc(52px + var(--safe-bottom))) + 16px);
  }
}
</style>
