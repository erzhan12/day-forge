<script setup lang="ts">
import type { ScheduleSettingsWire } from "../../types"
import DayWindowEditor from "../DayWindowEditor.vue"

defineProps<{ window: ScheduleSettingsWire }>()
</script>

<template>
  <section class="settings-panel">
    <h2 id="settings-topic-schedule" class="settings-topic-heading" tabindex="-1">Schedule</h2>
    <DayWindowEditor :window="window" />
  </section>
</template>

<style scoped>
.settings-panel { display: flex; flex-direction: column; gap: 16px; }
h2 { margin: 0; color: var(--text-primary); }
h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
</style>
