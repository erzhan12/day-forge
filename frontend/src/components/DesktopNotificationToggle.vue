<script setup lang="ts">
import { useDesktopNotificationSetting } from "../composables/useDesktopNotifications"

// Presentational toggle for the opt-in desktop-notification feature (issue
// #100 / feature 0028). All state + persistence + the permission request live
// in the composable; this component renders the switch, forwards changes, and
// owns the mandatory DOM resync (see onChange).
const { enabled, setEnabled, permissionDenied, notSupported } =
  useDesktopNotificationSetting()

async function onChange(event: Event) {
  const el = event.target as HTMLInputElement
  await setEnabled(el.checked)
  // Mandatory DOM resync: `:checked="enabled"` is a one-way bind, so when a
  // click resolves to denied/default and `enabled` was already false (a
  // REPEATED denied attempt — neither `enabled` nor `permissionDenied`
  // changes), Vue skips the patch and the user-checked box would stay visually
  // ON while the setting is OFF. The explicit write corrects the DOM even when
  // no reactive ref changed.
  el.checked = enabled.value
}
</script>

<template>
  <section class="desktop-section" aria-labelledby="desktop-heading">
    <h2 id="desktop-heading" class="section-title">Desktop notifications</h2>
    <p class="section-subtitle">
      Show a browser desktop notification when a block reaches its start time
      and another when it reaches its end time, while the schedule is open.
      Off by default; the setting is saved on this device only.
    </p>

    <label class="desktop-toggle">
      <input
        type="checkbox"
        role="switch"
        :checked="enabled"
        :aria-checked="enabled"
        :disabled="notSupported"
        @change="onChange"
      />
      <span class="desktop-toggle__label">
        {{ enabled ? "On" : "Off" }}
      </span>
    </label>

    <p v-if="notSupported" class="desktop-hint">
      This browser doesn't support desktop notifications.
    </p>
    <p v-else-if="permissionDenied" class="desktop-hint">
      Browser blocked notifications. Allow them in site settings and try again.
    </p>
  </section>
</template>

<style scoped>
.desktop-section {
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

.desktop-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-primary);
}

.desktop-toggle input {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--accent);
}

.desktop-toggle input:disabled {
  cursor: not-allowed;
}

.desktop-toggle__label {
  user-select: none;
}

.desktop-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}
</style>
