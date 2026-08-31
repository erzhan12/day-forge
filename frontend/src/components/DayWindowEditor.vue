<script setup lang="ts">
import { ref, watch } from "vue"
import { router } from "@inertiajs/vue3"
import { requestJson } from "../composables/useHttp"
import { timeZoneOptions } from "../utils/timeZones"

const props = defineProps<{ window: { start: string; end: string; time_zone: string } }>()
const start = ref(props.window.start)
const end = ref(props.window.end)
const timeZone = ref(props.window.time_zone)
const saving = ref(false)
const errors = ref<Record<string, string | string[]>>({})

watch(() => props.window, (value) => {
  start.value = value.start
  end.value = value.end
  timeZone.value = value.time_zone
  errors.value = {}
}, { deep: true })

function validate() {
  const next: Record<string, string> = {}
  const pattern = /^([01]\d|2[0-3]):[0-5]\d$/
  if (!pattern.test(start.value)) next.day_start = "Use HH:MM format."
  if (!pattern.test(end.value)) next.day_end = "Use HH:MM format."
  if (!next.day_start && Number(start.value.slice(3)) % 5) next.day_start = "Use 5-minute increments."
  if (!next.day_end && Number(end.value.slice(3)) % 5) next.day_end = "Use 5-minute increments."
  if (!Object.keys(next).length && start.value >= end.value) next.day_end = "End must be after start."
  errors.value = next
  return !Object.keys(next).length
}

async function save() {
  if (!validate()) return
  saving.value = true
  const result = await requestJson("/api/user/schedule-settings/", "PATCH", { day_start: start.value, day_end: end.value, time_zone: timeZone.value })
  saving.value = false
  if (!result.ok) {
    errors.value = result.errors ?? { detail: "Unable to save day window." }
    start.value = props.window.start
    end.value = props.window.end
    timeZone.value = props.window.time_zone
    return
  }
  router.reload({ only: ["schedule_window"] })
}
</script>

<template>
  <section class="day-window-editor" aria-label="Day window">
    <h3 class="section-title">Day window</h3>
    <p class="section-subtitle">Choose the hours used for scheduling and timeline gaps.</p>
    <div class="inputs">
      <label>Start <input v-model="start" type="time" step="300" :disabled="saving" /></label>
      <label>End <input v-model="end" type="time" step="300" :disabled="saving" /></label>
      <label>Timezone <select v-model="timeZone" :disabled="saving"><option v-for="zone in timeZoneOptions(timeZone)" :key="zone" :value="zone">{{ zone }}</option></select></label>
      <button type="button" :disabled="saving" @click="save">{{ saving ? "Saving…" : "Save" }}</button>
    </div>
    <p v-for="(message, field) in errors" :key="field" class="error">{{ Array.isArray(message) ? message.join(" ") : message }}</p>
  </section>
</template>

<style scoped>
.inputs { display:flex; gap:10px; align-items:end; flex-wrap:wrap; }
label { display:flex; flex-direction:column; gap:4px; font-size:13px; }
input, select, button { padding:6px 8px; border:1px solid var(--border-strong); border-radius:6px; background:var(--bg-page); color:var(--text-primary); }
button { cursor:pointer; background:var(--accent); color:var(--bg-page); }
.error { color:var(--danger-text); font-size:13px; margin:6px 0 0; }
</style>
