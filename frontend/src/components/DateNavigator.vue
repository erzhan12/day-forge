<script setup lang="ts">
import { computed } from "vue"
import { router } from "@inertiajs/vue3"
import { parseLocalDate, toLocalDateString, todayString } from "../utils/date"

const props = defineProps<{
  date: string
}>()

const formatted = computed(() => {
  const d = parseLocalDate(props.date)
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  })
})

const today = computed(() => todayString())

function offsetDate(offset: number): string {
  const d = parseLocalDate(props.date)
  d.setDate(d.getDate() + offset)
  return toLocalDateString(d)
}

function navigate(date: string) {
  router.visit(`/schedule/${date}/`)
}
</script>

<template>
  <nav class="date-navigator">
    <button class="nav-btn" @click="navigate(offsetDate(-1))">&#8249;</button>
    <div class="date-display">
      <span class="date-text">{{ formatted }}</span>
      <button
        v-if="date !== today"
        class="today-btn"
        @click="navigate(today)"
      >
        Today
      </button>
    </div>
    <button class="nav-btn" @click="navigate(offsetDate(1))">&#8250;</button>
  </nav>
</template>

<style scoped>
.date-navigator {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  background: white;
}

.nav-btn {
  width: 40px;
  height: 40px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: white;
  font-size: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #374151;
}

.nav-btn:hover {
  background: #f3f4f6;
}

.date-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.date-text {
  font-size: 18px;
  font-weight: 600;
  color: #111827;
}

.today-btn {
  font-size: 12px;
  padding: 2px 10px;
  border: 1px solid #d1d5db;
  border-radius: 12px;
  background: white;
  color: #6b7280;
}

.today-btn:hover {
  background: #f3f4f6;
}

</style>
