<script setup lang="ts">
import { computed, ref } from "vue"
import { router } from "@inertiajs/vue3"
import { requestJson } from "../composables/useHttp"
import { extractErrorMessage } from "../utils/errorMessage"
import { isTimeZoneHandled, markTimeZoneHandled } from "../utils/timeZoneMismatchStorage"
import { browserTimeZone } from "../utils/timeZones"

const props = defineProps<{ timeZone: string }>()
const detected = browserTimeZone()
const busy = ref(false)
const error = ref<string | null>(null)
const dismissed = ref(detected ? isTimeZoneHandled(detected) : true)
const visible = computed(() => Boolean(detected && detected !== props.timeZone && !dismissed.value))

function dismiss(): void {
  if (detected) markTimeZoneHandled(detected)
  dismissed.value = true
}

async function update(): Promise<void> {
  if (!detected) return
  busy.value = true
  error.value = null
  const result = await requestJson("/api/user/schedule-settings/", "PATCH", { time_zone: detected })
  busy.value = false
  if (!result.ok) {
    error.value = extractErrorMessage(result.errors, "Unable to update timezone.")
    return
  }
  markTimeZoneHandled(detected)
  dismissed.value = true
  router.reload({ only: ["schedule_window"] })
}
</script>

<template>
  <aside v-if="visible" class="timezone-mismatch" role="status">
    <span>Your timezone looks like {{ detected }} — update your settings?</span>
    <button type="button" :disabled="busy" @click="update">{{ busy ? "Updating…" : "Update" }}</button>
    <button type="button" :disabled="busy" @click="dismiss">Dismiss</button>
    <p v-if="error" class="error">{{ error }}</p>
  </aside>
</template>

<style scoped>
.timezone-mismatch { display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:10px 14px; background:var(--bg-raised); border:1px solid var(--border-strong); border-radius:8px; color:var(--text-primary); }
button { padding:5px 9px; border:1px solid var(--border-strong); border-radius:6px; background:var(--bg-page); color:var(--text-primary); cursor:pointer; }
.error { width:100%; margin:0; color:var(--danger-text); }
</style>
