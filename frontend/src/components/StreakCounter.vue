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
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid #fcd34d;
}
.emoji {
  font-size: 13px;
}
</style>
