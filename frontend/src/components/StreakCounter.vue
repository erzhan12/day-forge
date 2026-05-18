<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{
  streak: number
  threshold: number
}>()

const tooltip = computed(
  () => `Days with ≥ ${Math.round(props.threshold * 100)}% completion`,
)
</script>

<template>
  <span class="streak-pill" :title="tooltip">
    <span v-if="streak > 0" class="emoji" aria-hidden="true">🔥</span>
    <span class="text">{{ streak }}-day streak</span>
  </span>
</template>

<style scoped>
.streak-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--warning-surface);
  color: var(--warning-text);
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--warning-border);
}
.emoji {
  font-size: 13px;
}
</style>
