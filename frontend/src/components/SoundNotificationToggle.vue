<script setup lang="ts">
import { useSoundNotificationSetting } from "../composables/useSoundNotifications"

// Presentational toggle for the opt-in sound-notification feature (issue
// #56). All state + persistence + the autoplay unlock live in the
// composable; this component only renders the switch and forwards changes.
// The `@change` handler runs inside the user click gesture, so
// `setEnabled(true)` can resume the shared AudioContext (autoplay policy).
const { enabled, setEnabled } = useSoundNotificationSetting()

function onChange(event: Event) {
  setEnabled((event.target as HTMLInputElement).checked)
}
</script>

<template>
  <section class="sound-section" aria-labelledby="sound-heading">
    <h2 id="sound-heading" class="section-title">Sound notifications</h2>
    <p class="section-subtitle">
      Play a short chime when a block reaches its start time and another when
      it reaches its end time. Off by default; the setting is saved on this
      device only.
    </p>

    <label class="sound-toggle">
      <input
        type="checkbox"
        role="switch"
        :checked="enabled"
        :aria-checked="enabled"
        @change="onChange"
      />
      <span class="sound-toggle__label">
        {{ enabled ? "On" : "Off" }}
      </span>
    </label>
  </section>
</template>

<style scoped>
.sound-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  margin: 0;
  font-size: 18px;
  color: var(--text-primary);
}

.section-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.sound-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-primary);
}

.sound-toggle input {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--accent);
}

.sound-toggle__label {
  user-select: none;
}
</style>
