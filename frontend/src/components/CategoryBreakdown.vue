<script setup lang="ts">
import { computed } from "vue"
import type { CategoryMinutes, UserCategory } from "../types"
import { getCategoryColor } from "../utils/categoryColors"
import { useActiveTheme } from "../composables/useActiveTheme"
import { timeToMinutes } from "../utils/scheduleTime"
import { orderedCategories } from "../utils/categories"

// Reactive dep so the rows computed re-runs when the user switches
// themes (shared with TimeBlock / SkippedTasks; see composable).
const activeTheme = useActiveTheme()

const props = defineProps<{
  planned: CategoryMinutes
  completed: CategoryMinutes
  windowStart?: string
  windowEnd?: string
  categories?: UserCategory[]
}>()

// Render in a stable order so the layout doesn't reshuffle as values
// change. The keys come from the existing TimeBlock category union; if
// a category is added, this list (and the type) need to be updated
// together.
const categoryOrder = computed(() => orderedCategories(props.categories ?? []))

// Day-window minutes (06:00–23:00 = 1020 by default) — the reference
// the planned bars are normalised against. Phase 6 plan: planned width
// = total minutes / day-window-minutes. Communicates absolute time
// invested across the day, not just the relative ranking of categories.
const dayWindowMinutes = computed(() => timeToMinutes(props.windowEnd ?? "23:00") - timeToMinutes(props.windowStart ?? "06:00"))

const totalPlanned = computed(() =>
  categoryOrder.value.reduce((sum, key) => sum + (props.planned[key.slug] || 0), 0),
)

interface Row {
  key: string
  label: string
  planned: number
  completed: number
  // Bar width as a percentage of the visible day window. A category
  // taking 240/1020 minutes renders ~24% wide, regardless of how the
  // other categories compare.
  plannedPct: number
  completedPctOfPlanned: number
  // Resolved hex (may differ from the base palette under a theme that
  // overrides this category for WCAG 3:1 — see categoryColors.ts).
  color: string
}

const rows = computed<Row[]>(() => {
  // Read once so all three usages (swatch, alpha tint, solid bar) share
  // the same resolved color and a future theme change re-derives them
  // together.
  const theme = activeTheme.value
  return categoryOrder.value.map((key) => {
    const planned = props.planned[key.slug] || 0
    const completed = props.completed[key.slug] || 0
    return {
      key: key.slug,
      label: key.label,
      planned,
      completed,
      plannedPct: Math.min(100, (planned / dayWindowMinutes.value) * 100),
      completedPctOfPlanned:
        planned > 0 ? Math.min(100, (completed / planned) * 100) : 0,
      color: getCategoryColor(key.slug, theme, props.categories),
    }
  })
})

function formatMinutes(m: number): string {
  if (m === 0) return "0m"
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const rem = m % 60
  return rem > 0 ? `${h}h ${rem}m` : `${h}h`
}
</script>

<template>
  <section class="category-breakdown" aria-label="Category breakdown">
    <header class="header">
      <h3>By category</h3>
      <span class="total">{{ formatMinutes(totalPlanned) }} planned</span>
    </header>
    <ul class="rows">
      <li v-for="row in rows" :key="row.key" class="row">
        <span class="label">
          <span class="swatch" :style="{ background: row.color }" />
          {{ row.label }}
        </span>
        <div class="bar-track">
          <div
            class="bar-planned"
            :style="{
              width: `${row.plannedPct}%`,
              background: `${row.color}33`,
            }"
          >
            <div
              class="bar-completed"
              :style="{
                width: `${row.completedPctOfPlanned}%`,
                background: row.color,
              }"
            />
          </div>
        </div>
        <span class="minutes">
          {{ formatMinutes(row.completed) }} / {{ formatMinutes(row.planned) }}
        </span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.category-breakdown {
  background: var(--bg-panel);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
}
.header h3 {
  margin: 0;
  font-size: 14px;
  color: var(--text-primary);
}
.total {
  font-size: 12px;
  color: var(--text-muted);
}
.rows {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}
.row {
  display: grid;
  grid-template-columns: 80px 1fr 100px;
  align-items: center;
  gap: 8px;
}
.label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.bar-track {
  background: var(--bg-schedule-gap);
  height: 12px;
  border-radius: 6px;
  overflow: hidden;
  position: relative;
}
.bar-planned {
  height: 100%;
  border-radius: 6px;
  position: relative;
}
.bar-completed {
  height: 100%;
  border-radius: 6px;
}
.minutes {
  text-align: right;
  font-size: 11px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
</style>
