<script setup lang="ts">
import { computed } from "vue"
import { Link, router } from "@inertiajs/vue3"
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
      <slot name="status" />
    </div>
    <div class="right-controls">
      <slot name="actions" />
      <Link href="/settings/" class="nav-btn settings-btn" aria-label="Settings">
        <span aria-hidden="true">⚙</span>
      </Link>
      <button class="nav-btn" @click="navigate(offsetDate(1))">&#8250;</button>
    </div>
  </nav>
</template>

<style scoped>
.date-navigator {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  background: var(--bg-panel);
}

.nav-btn {
  width: 40px;
  height: 40px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-panel);
  font-size: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}

.nav-btn:hover {
  background: var(--bg-schedule-gap);
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
  color: var(--text-primary);
}

.today-btn {
  font-size: 12px;
  padding: 2px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 12px;
  background: var(--bg-panel);
  color: var(--text-muted);
}

.today-btn:hover {
  background: var(--bg-schedule-gap);
}

.right-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.settings-btn {
  text-decoration: none;
  color: var(--text-secondary);
}

.settings-btn:hover {
  background: var(--bg-schedule-gap);
}
</style>
