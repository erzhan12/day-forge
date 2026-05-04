<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{
  completed: number
  planned: number
}>()

const isRestDay = computed(() => props.planned === 0)
const ratio = computed(() =>
  isRestDay.value ? 0 : Math.round((props.completed / props.planned) * 100),
)
</script>

<template>
  <section class="completion-bar" aria-label="Completion summary">
    <template v-if="isRestDay">
      <p class="rest-day">Rest day — nothing planned.</p>
    </template>
    <template v-else>
      <header class="header">
        <span class="ratio">{{ completed }}/{{ planned }}</span>
        <span class="percent">{{ ratio }}%</span>
      </header>
      <div class="track" :aria-valuenow="ratio" aria-valuemin="0" aria-valuemax="100" role="progressbar">
        <div class="fill" :style="{ width: `${ratio}%` }" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.completion-bar {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.rest-day {
  margin: 0;
  font-size: 14px;
  color: #6b7280;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}
.ratio {
  font-size: 13px;
  color: #6b7280;
}
.percent {
  font-size: 20px;
  font-weight: 600;
  color: #111827;
}
.track {
  height: 10px;
  background: #f3f4f6;
  border-radius: 999px;
  overflow: hidden;
}
.fill {
  height: 100%;
  background: #10b981;
  transition: width 200ms ease;
}
</style>
