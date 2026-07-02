<script setup lang="ts">
import { useExternalCalendarPlacement } from "../composables/useExternalCalendarPlacement"
import type { ExternalCalendarPlacement } from "../utils/externalCalendarPlacementStorage"

const { placement, setPlacement } = useExternalCalendarPlacement()

function onChange(event: Event) {
  setPlacement((event.target as HTMLInputElement).value as ExternalCalendarPlacement)
}
</script>

<template>
  <div class="placement-toggle" aria-labelledby="calendar-placement-heading">
    <h3 id="calendar-placement-heading" class="subsection-title">
      Event panel placement
    </h3>
    <p class="section-subtitle">
      Choose where external calendar events appear on the schedule page. Saved
      on this device only.
    </p>

    <label class="placement-option">
      <input
        type="radio"
        name="external-calendar-placement"
        value="sidebar"
        :checked="placement === 'sidebar'"
        @change="onChange"
      />
      <span>Left sidebar (with Todoist)</span>
    </label>

    <label class="placement-option">
      <input
        type="radio"
        name="external-calendar-placement"
        value="center"
        :checked="placement === 'center'"
        @change="onChange"
      />
      <span>Center column (above the schedule)</span>
    </label>
  </div>
</template>

<style scoped>
.placement-toggle {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.subsection-title {
  margin: 0;
  font-size: 15px;
  color: var(--text-primary);
}

.section-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.placement-option {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--text-primary);
  cursor: pointer;
}

.placement-option input {
  accent-color: var(--accent);
  cursor: pointer;
}
</style>
