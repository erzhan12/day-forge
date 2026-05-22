<script setup lang="ts">
import { computed, toRef } from "vue"
import type { TimeBlock } from "../types"
import { getCategoryColor } from "../utils/categoryColors"
import { useActiveTheme } from "../composables/useActiveTheme"
import { todayString } from "../utils/date"
import { useNowMinutes } from "../composables/useNowMinutes"

const props = defineProps<{
  blocks: TimeBlock[]
  date: string
}>()

const activeTheme = useActiveTheme()
// Shared 60s tick so today's blocks roll into Skipped as their window closes
// (extracted from the previously duplicated Schedule.vue interval).
const { currentHHMM } = useNowMinutes(toRef(props, "date"))

const isPastDay = computed(() => props.date < todayString())
const isToday = computed(() => props.date === todayString())

const skipped = computed<TimeBlock[]>(() => {
  if (!isPastDay.value && !isToday.value) return []
  return props.blocks.filter((b) => {
    if (b.is_completed) return false
    if (isPastDay.value) return true
    // Today: only blocks whose end_time has passed are considered skipped.
    // Future-window uncompleted blocks are still active.
    return b.end_time < currentHHMM.value
  })
})

</script>

<template>
  <section v-if="skipped.length" class="skipped-tasks" aria-label="Skipped tasks">
    <h3>Skipped</h3>
    <ul>
      <li v-for="b in skipped" :key="b.id" class="skipped-row">
        <span
          class="swatch"
          :style="{ background: getCategoryColor(b.category, activeTheme) }"
          aria-hidden="true"
        />
        <span class="time">{{ b.start_time }}–{{ b.end_time }}</span>
        <span class="title">{{ b.title }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.skipped-tasks {
  background: var(--bg-panel);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.skipped-tasks h3 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--text-primary);
}
ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 6px;
}
.skipped-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: var(--danger-surface);
  border-radius: 6px;
  font-size: 13px;
}
.swatch {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex-shrink: 0;
}
.time {
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.title {
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
