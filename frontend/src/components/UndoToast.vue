<script setup lang="ts">
withDefaults(
  defineProps<{
    message: string
    actionable?: boolean
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
    <div class="undo-toast">
      <span class="toast-message">{{ message }}</span>
      <button v-if="actionable !== false" class="toast-undo-btn" @click="emit('undo')">Undo</button>
      <button class="toast-close-btn" @click="emit('dismiss')">&times;</button>
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
  color: #9ca3af;
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
  background: #3b82f6;
  animation: shrink 8s linear forwards;
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
</style>
