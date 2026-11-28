<script setup lang="ts">
// Dark 4a mobile header (feature 0113, SPEC 11.2): one 56 px row with
// previous day, centred date, next day and the gear menu. Undo, Show
// indicator, Today, draft badge and Regenerate draft are not rendered here.
import { computed, nextTick, ref } from "vue"
import { router } from "@inertiajs/vue3"
import { addCivilDays, formatMobileHeaderDate } from "../utils/date"
import MobileMenu from "./MobileMenu.vue"

const props = defineProps<{
  date: string
  showAnalytics: boolean
  showCalendars: boolean
}>()

const emit = defineEmits<{ calendars: []; logout: [] }>()

const label = computed(() => formatMobileHeaderDate(props.date))
const menuOpen = ref(false)
const gear = ref<HTMLButtonElement | null>(null)

function navigate(offset: number): void {
  router.visit(`/schedule/${addCivilDays(props.date, offset)}/`)
}

function closeMenu(): void {
  menuOpen.value = false
}

function openCalendars(): void {
  menuOpen.value = false
  emit("calendars")
}

function logout(): void {
  menuOpen.value = false
  emit("logout")
}

async function focusGear(): Promise<void> {
  await nextTick()
  gear.value?.focus()
}

defineExpose({ focusGear })
</script>

<template>
  <header class="mobile-header" data-testid="mobile-header">
    <div class="cell cell-start">
      <button type="button" class="hit" aria-label="Previous day" data-testid="mobile-prev" @click="navigate(-1)">
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
      </button>
    </div>
    <h1 class="mobile-date" data-testid="mobile-date">{{ label }}</h1>
    <div class="cell cell-end">
      <button type="button" class="hit" aria-label="Next day" data-testid="mobile-next" @click="navigate(1)">
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>
      </button>
      <button
        ref="gear"
        type="button"
        class="hit"
        aria-label="Menu"
        aria-haspopup="dialog"
        :aria-expanded="menuOpen"
        data-testid="mobile-gear"
        @click="menuOpen = true"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
      </button>
    </div>
    <MobileMenu
      v-if="menuOpen"
      :date="props.date"
      :show-analytics="props.showAnalytics"
      :show-calendars="props.showCalendars"
      @close="closeMenu(); focusGear()"
      @calendars="openCalendars"
      @logout="logout"
    />
  </header>
</template>

<style scoped>
html[data-theme="dark_4a"] .mobile-header {
  /* The body is padded by the safe-area insets; cancel the top one so the
     header's own padding paints the status-bar area (SPEC 11.2). */
  position: sticky;
  top: 0;
  z-index: 40;
  box-sizing: border-box;
  display: grid;
  grid-template-columns: 88px 1fr 88px;
  align-items: center;
  height: calc(56px + var(--safe-top));
  margin-top: calc(-1 * var(--safe-top));
  padding-top: var(--safe-top);
  background: #1f2023;
  border-bottom: 1px solid #34363b;
}

html[data-theme="dark_4a"] .cell {
  display: flex;
  align-items: center;
}

html[data-theme="dark_4a"] .cell-end {
  justify-content: flex-end;
}

html[data-theme="dark_4a"] .mobile-date {
  margin: 0;
  text-align: center;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.2;
  color: #e5e7eb;
  white-space: nowrap;
}

html[data-theme="dark_4a"] .hit {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #e5e7eb;
}

html[data-theme="dark_4a"] .hit:focus-visible {
  outline: 2px solid #fd7562;
  outline-offset: -4px;
  border-radius: 8px;
}
</style>
