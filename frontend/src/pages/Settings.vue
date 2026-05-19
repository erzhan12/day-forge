<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue"
import { Link, router } from "@inertiajs/vue3"
import type { Rule, Template } from "../types"
import TemplateEditor from "../components/TemplateEditor.vue"
import RulesList from "../components/RulesList.vue"
import DesignSelector from "../components/DesignSelector.vue"
import { todayString } from "../utils/date"
// Keeps `<html data-theme>` in sync with ui_preferences across reloads.
// Required convention for every authenticated page — see RULES.md.
import { useThemeFromProps } from "../composables/useThemeFromProps"
import { useCalendarAccount } from "../composables/useCalendarAccount"
import "../app.css"

useThemeFromProps()

const props = defineProps<{
  templates: Template[]
  rules: Rule[]
}>()

const localTemplates = ref<Template[]>(props.templates.map((t) => ({ ...t })))
const localRules = ref<Rule[]>(props.rules.map((r) => ({ ...r })))

watch(
  () => props.templates,
  (next) => {
    localTemplates.value = next.map((t) => ({ ...t }))
  },
  { deep: true },
)
watch(
  () => props.rules,
  (next) => {
    localRules.value = next.map((r) => ({ ...r }))
  },
  { deep: true },
)

const weekdayTemplate = computed(
  () => localTemplates.value.find((t) => t.type === "weekday") ?? null,
)
const weekendTemplate = computed(
  () => localTemplates.value.find((t) => t.type === "weekend") ?? null,
)

function refreshTemplates() {
  router.reload({ only: ["templates"] })
}
function refreshRules() {
  router.reload({ only: ["rules"] })
}

const today = todayString()

// ---------------------------------------------------------------------------
// Apple Calendar (feature 0011) — connect / disconnect via CalDAV.
// ---------------------------------------------------------------------------
const calendarAccount = useCalendarAccount()

const calendarForm = reactive<{ apple_id: string; password: string; base_url: string }>({
  apple_id: "",
  password: "",
  base_url: "",
})
const showAdvanced = ref(false)
const calendarMessage = ref<string | null>(null)

onMounted(() => {
  calendarAccount.fetchAccountStatus()
})

const isCalendarConnected = computed(() =>
  Boolean(calendarAccount.state.status?.connected),
)
const calendarBusy = computed(
  () => calendarAccount._internals.accountOperationInFlight.value !== null,
)
const calendarDefaultBaseUrl = computed(
  () => calendarAccount.state.status?.default_base_url ?? "",
)

async function handleCalendarConnect() {
  calendarMessage.value = null
  const result = await calendarAccount.connect({
    apple_id: calendarForm.apple_id.trim(),
    password: calendarForm.password,
    base_url: calendarForm.base_url.trim() || undefined,
  })
  if (result.ok) {
    calendarForm.password = ""
    calendarMessage.value = "Apple Calendar connected."
  }
}

async function handleCalendarDisconnect() {
  calendarMessage.value = null
  const result = await calendarAccount.disconnect()
  if (result.ok) {
    calendarForm.apple_id = ""
    calendarForm.password = ""
    calendarForm.base_url = ""
    calendarMessage.value = "Apple Calendar disconnected."
  }
}
</script>

<template>
  <div class="settings-page">
    <header class="page-header">
      <Link :href="`/schedule/${today}/`" class="back-link">← Back to schedule</Link>
      <h1>Settings</h1>
    </header>

    <section class="section">
      <DesignSelector />
    </section>

    <section class="section">
      <h2 class="section-title">Templates</h2>
      <p class="section-subtitle">
        One template per day type. The active template is the baseline for
        each new day's auto-generated draft.
      </p>
      <div class="template-grid">
        <TemplateEditor
          :template="weekdayTemplate"
          slot-type="weekday"
          @saved="refreshTemplates"
          @deleted="refreshTemplates"
        />
        <TemplateEditor
          :template="weekendTemplate"
          slot-type="weekend"
          @saved="refreshTemplates"
          @deleted="refreshTemplates"
        />
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Rules</h2>
      <p class="section-subtitle">
        Active rules are passed to the AI when generating drafts. Higher
        priority rules take precedence on conflict.
      </p>
      <RulesList :rules="localRules" @changed="refreshRules" />
    </section>

    <section class="section">
      <h2 class="section-title">Apple Calendar</h2>
      <p class="section-subtitle">
        Connect via CalDAV to display Apple Calendar events alongside the
        daily schedule (read-only). Use an
        <a
          href="https://support.apple.com/en-us/HT204397"
          target="_blank"
          rel="noopener noreferrer"
        >Apple ID app-specific password</a> — Day Forge never reads
        two-factor codes.
      </p>

      <p v-if="isCalendarConnected" class="cal-status connected">
        Connected as
        <strong>{{ calendarAccount.state.status?.apple_id }}</strong>
      </p>
      <p v-else class="cal-status">Not connected</p>

      <p
        v-if="calendarAccount.state.error"
        class="cal-error"
        role="status"
      >
        {{ calendarAccount.state.error }}
      </p>
      <p
        v-else-if="calendarMessage"
        class="cal-message"
        role="status"
      >
        {{ calendarMessage }}
      </p>

      <form
        v-if="!isCalendarConnected"
        class="cal-form"
        @submit.prevent="handleCalendarConnect"
      >
        <label class="cal-field">
          <span>Apple ID</span>
          <input
            v-model="calendarForm.apple_id"
            type="email"
            autocomplete="username"
            required
            :disabled="calendarBusy"
          />
        </label>
        <label class="cal-field">
          <span>App-specific password</span>
          <input
            v-model="calendarForm.password"
            type="password"
            autocomplete="new-password"
            required
            :disabled="calendarBusy"
          />
        </label>
        <button
          type="button"
          class="cal-advanced-toggle"
          @click="showAdvanced = !showAdvanced"
        >
          {{ showAdvanced ? "Hide" : "Show" }} advanced
        </button>
        <label v-if="showAdvanced" class="cal-field">
          <span>CalDAV base URL</span>
          <input
            v-model="calendarForm.base_url"
            type="url"
            :placeholder="calendarDefaultBaseUrl"
            :disabled="calendarBusy"
          />
        </label>
        <button
          type="submit"
          class="cal-submit"
          :disabled="calendarBusy"
        >
          {{ calendarBusy ? "Connecting…" : "Connect" }}
        </button>
      </form>

      <button
        v-else
        type="button"
        class="cal-disconnect"
        :disabled="calendarBusy"
        @click="handleCalendarDisconnect"
      >
        {{ calendarBusy ? "Disconnecting…" : "Disconnect" }}
      </button>
    </section>
  </div>
</template>

<style scoped>
.settings-page {
  /* max-width grows with the viewport: a single 720px column on
     narrow/laptop screens, but expanding to 1024px on desktop where
     the 2-column ``.template-grid`` kicks in. Without this widening,
     two cards inside a 720px page get ~352px each — too narrow for
     the 5-column blocks form. See the playwright repro at
     scripts/playwright/template-editor-layout.mjs. */
  max-width: 720px;
  margin: 0 auto;
  padding: 24px 16px 80px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

@media (min-width: 1024px) {
  .settings-page {
    max-width: 1024px;
  }
}

.page-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.back-link {
  font-size: 13px;
  color: var(--accent);
  text-decoration: none;
}

.back-link:hover {
  text-decoration: underline;
}

.page-header h1 {
  margin: 0;
  font-size: 26px;
  color: var(--text-primary);
  font-family: var(--font-family-display);
}

.section {
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

.template-grid {
  display: grid;
  gap: 16px;
}

/* Two-column only on truly wide viewports. At 720px each card gets
   ~320px which can't fit the 5-column blocks form (Title + Start +
   End + Category + delete = ~370px minimum). Lifting to 1024px keeps
   side-by-side layout for desktop-class screens (where ``max-width:
   720px`` of the page already constrains the page itself, so each
   card lands at ~352px) — the page-level max-width still leaves us
   tight, so we also need the form-row CSS in TemplateEditor.
   See the playwright repro at scripts/playwright/template-editor-layout.mjs. */
@media (min-width: 1024px) {
  .template-grid {
    grid-template-columns: 1fr 1fr;
  }
}

.cal-status {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.cal-status.connected {
  color: var(--text-primary);
}

.cal-error {
  margin: 0;
  padding: 8px 10px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
  font-size: 13px;
}

.cal-message {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.cal-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  padding: 12px;
}

.cal-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.cal-field input {
  font-size: 14px;
  padding: 6px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--bg-page);
  color: var(--text-primary);
}

.cal-advanced-toggle {
  align-self: flex-start;
  background: none;
  border: none;
  padding: 0;
  color: var(--accent);
  cursor: pointer;
  font-size: 12px;
}

.cal-submit,
.cal-disconnect {
  align-self: flex-start;
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--accent);
  color: var(--bg-page);
  cursor: pointer;
  font-size: 13px;
}

.cal-disconnect {
  background: var(--bg-panel);
  color: var(--danger-text);
  border-color: var(--danger-border);
}

.cal-submit:disabled,
.cal-disconnect:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
