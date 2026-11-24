<script setup lang="ts">
import { computed, onMounted } from "vue"
import { useDailyExportToken } from "../../composables/useDailyExportToken"
import { zonedDateTime } from "../../utils/date"

const props = defineProps<{
  authUserId?: number | null
  timeZone?: string
}>()

const token = useDailyExportToken()

// Same "YYYY-MM-DD HH:MM" local format as the integrations' "verified" stamps.
// An unparseable value is shown as-is rather than as "NaN".
const createdAtLabel = computed(() => {
  const raw = token.state.createdAt
  if (!raw) return null
  const instant = new Date(raw)
  if (Number.isNaN(instant.getTime())) return raw
  const local = zonedDateTime(instant, props.timeZone ?? "UTC")
  return `${local.date} ${local.hhmm}`
})

onMounted(() => {
  token.fetchStatus()
})

async function handleCreate(): Promise<void> {
  await token.createToken(props.authUserId ?? undefined)
}

async function handleRevoke(): Promise<void> {
  await token.revokeToken(props.authUserId ?? undefined)
}

function handleDismiss(): void {
  token.dismissRawToken()
}

function selectValue(event: Event): void {
  ;(event.target as HTMLInputElement).select()
}
</script>

<template>
  <section class="settings-panel daily-export-token-panel" data-testid="settings-integration-export-token">
    <h3 class="subsection-title">Daily export API token</h3>
    <p class="section-subtitle">
      A personal, read-only token for <code>GET /api/export/daily/&lt;date&gt;/</code>
      and <code>GET /api/export/whoop/&lt;date&gt;/</code>. It only authorizes these two
      export endpoints — it cannot edit your schedule or manage this token itself.
      If WHOOP is connected, it also reads your WHOOP sleep and recovery summary,
      so treat it as access to health data.
    </p>

    <p v-if="token.state.error" role="alert" class="export-token-error">
      {{ token.state.error }}
    </p>

    <div v-if="token.state.rawToken" class="export-token-reveal" data-testid="export-token-reveal">
      <p class="export-token-shown-once">
        Shown once — copy it now. It will not be shown again.
      </p>
      <input
        type="text"
        readonly
        class="export-token-value df-field"
        data-testid="export-token-value"
        :value="token.state.rawToken"
        @click="selectValue"
      />
      <button type="button" class="export-token-action df-btn df-btn--field" data-testid="export-token-dismiss" @click="handleDismiss">
        I've saved it
      </button>
    </div>

    <div v-else class="export-token-controls">
      <p v-if="token.state.hasToken === true" class="export-token-status" data-testid="export-token-status">
        Active since {{ createdAtLabel }}
      </p>
      <p
        v-else-if="token.state.hasToken === false"
        class="export-token-status"
        data-testid="export-token-status"
      >
        No token yet.
      </p>
      <p v-else class="export-token-status" data-testid="export-token-status">Loading…</p>

      <button
        v-if="!token.state.hasToken"
        type="button"
        class="export-token-action export-token-create df-btn df-btn--primary"
        data-testid="export-token-create"
        :disabled="token.state.loading"
        @click="handleCreate"
      >
        Create token
      </button>
      <button
        v-else
        type="button"
        class="export-token-action export-token-revoke"
        data-testid="export-token-revoke"
        :disabled="token.state.loading"
        @click="handleRevoke"
      >
        Revoke token
      </button>
    </div>
  </section>
</template>

<style scoped>
/* Mirrors the integration blocks in SettingsIntegrationsPanel.vue and the
   divider of ExternalCalendarPlacementToggle.vue: their scoped type styles
   do not reach this separately mounted panel. */
.daily-export-token-panel,
.export-token-reveal,
.export-token-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.daily-export-token-panel {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.subsection-title { margin: 0; font-size: 18px; color: var(--text-primary); }
.section-subtitle { margin: 0; font-size: 13px; color: var(--text-muted); }
.export-token-error {
  margin: 0;
  padding: 8px 10px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
  font-size: 13px;
}
.export-token-status { margin: 0; font-size: 13px; color: var(--text-secondary); }
.export-token-shown-once { margin: 0; font-size: 13px; font-weight: 600; color: var(--text-primary); }
.export-token-value {
  box-sizing: border-box;
  width: 100%;
  font-family: monospace;
  font-size: 13px;
  padding: 6px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--bg-input);
  color: var(--text-primary);
}
/* Create / Revoke follow Connect / Disconnect (.cal-submit / .cal-disconnect). */
.export-token-action {
  align-self: flex-start;
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.export-token-create { background: var(--accent); color: var(--bg-page); }
.export-token-revoke {
  background: var(--bg-panel);
  color: var(--danger-text);
  border-color: var(--danger-border);
}
.export-token-action:disabled { opacity: 0.6; cursor: not-allowed; }

/* Dark 4a (feature 0106): Revoke keeps its danger colours at the shared
   36 px control height, like Disconnect; the shared field skin resets the
   token input's font, which keeps monospace digits here. */
html[data-theme="dark_4a"] .export-token-revoke {
  box-sizing: border-box;
  height: 36px;
  padding: 0 14px;
  font-size: 13px;
}
/* Revoke carries no .df-btn (that skin would change its weight and padding
   away from Disconnect), so it restates the shared Dark 4a focus ring. */
html[data-theme="dark_4a"] .export-token-revoke:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--focus-ring);
}
html[data-theme="dark_4a"] .export-token-value.df-field.df-field {
  font-family: monospace;
  font-size: 13px;
}
</style>
