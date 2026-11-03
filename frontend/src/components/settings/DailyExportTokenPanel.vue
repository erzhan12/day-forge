<script setup lang="ts">
import { onMounted } from "vue"
import { useDailyExportToken } from "../../composables/useDailyExportToken"

const props = defineProps<{
  authUserId?: number | null
}>()

const token = useDailyExportToken()

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
      A personal, read-only token for <code>GET /api/export/daily/&lt;date&gt;/</code>.
      It only authorizes that export endpoint — it cannot edit your schedule
      or manage this token itself.
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
        class="export-token-value"
        data-testid="export-token-value"
        :value="token.state.rawToken"
        @click="selectValue"
      />
      <button type="button" data-testid="export-token-dismiss" @click="handleDismiss">
        I've saved it
      </button>
    </div>

    <div v-else class="export-token-controls">
      <p v-if="token.state.hasToken === true" class="export-token-status" data-testid="export-token-status">
        Active since {{ token.state.createdAt }}
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
        data-testid="export-token-create"
        :disabled="token.state.loading"
        @click="handleCreate"
      >
        Create token
      </button>
      <button
        v-else
        type="button"
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
.daily-export-token-panel { margin-top: 24px; }
.export-token-error {
  margin: 0 0 8px;
  padding: 8px 10px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
  font-size: 13px;
}
.export-token-status { color: var(--text-secondary); font-size: 14px; }
.export-token-shown-once { font-weight: 600; color: var(--text-primary); }
.export-token-value {
  width: 100%;
  font-family: monospace;
  padding: 8px;
  margin: 8px 0;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text-primary);
}
</style>
