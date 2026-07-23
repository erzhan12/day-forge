<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue"
import { Link, router } from "@inertiajs/vue3"
import type { Rule, Template, TravelRule } from "../types"
import TemplateEditor from "../components/TemplateEditor.vue"
import RulesList from "../components/RulesList.vue"
import TravelRulesList from "../components/TravelRulesList.vue"
import DesignSelector from "../components/DesignSelector.vue"
import SoundNotificationToggle from "../components/SoundNotificationToggle.vue"
import DesktopNotificationToggle from "../components/DesktopNotificationToggle.vue"
import ExternalCalendarPlacementToggle from "../components/ExternalCalendarPlacementToggle.vue"
import { todayString } from "../utils/date"
// Keeps `<html data-theme>` in sync with ui_preferences across reloads.
// Required convention for every authenticated page — see RULES.md.
import { useThemeFromProps } from "../composables/useThemeFromProps"
import { useCalendarAccount } from "../composables/useCalendarAccount"
import { useGoogleAccount } from "../composables/useGoogleAccount"
import { useTodoistAccount } from "../composables/useTodoistAccount"
import { useHabiticaAccount } from "../composables/useHabiticaAccount"
import "../app.css"

useThemeFromProps()

const props = defineProps<{
  templates: Template[]
  rules: Rule[]
  travel_rules: TravelRule[]
}>()

const localTemplates = ref<Template[]>(props.templates.map((t) => ({ ...t })))
const localRules = ref<Rule[]>(props.rules.map((r) => ({ ...r })))
const localTravelRules = ref<TravelRule[]>(
  props.travel_rules.map((r) => ({ ...r })),
)

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
watch(
  () => props.travel_rules,
  (next) => {
    localTravelRules.value = next.map((r) => ({ ...r }))
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
function refreshTravelRules() {
  router.reload({ only: ["travel_rules"] })
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

// ---------------------------------------------------------------------------
// Google Calendar (feature 0022) — multi-account OAuth connect / disconnect.
// `connect()` is a full-page redirect (no fetch); the callback redirects back
// to /settings/?google=connected | error&reason=… which we surface as a toast.
// ---------------------------------------------------------------------------
const googleAccount = useGoogleAccount()
const googleMessage = ref<string | null>(null)
const googleError = ref<string | null>(null)

function googleErrorMessage(reason: string | null): string {
  switch (reason) {
    case "state":
      return "Session expired — sign in and connect Google again."
    case "denied":
      return "Google connection was cancelled."
    case "missing_code":
      return "Google returned an incomplete response. Try again."
    default:
      return "Could not connect Google Calendar. Try again."
  }
}

onMounted(() => {
  googleAccount.fetchAccounts()
  const params = new URLSearchParams(window.location.search)
  const google = params.get("google")
  if (google === "connected") {
    googleMessage.value = "Google Calendar connected."
    // Re-fetch so the just-connected account appears even if the mount fetch
    // above raced the OAuth redirect or transiently failed.
    googleAccount.fetchAccounts()
  } else if (google === "error") {
    googleError.value = googleErrorMessage(params.get("reason"))
  }
  if (google) {
    // Strip the one-shot callback params so a reload doesn't re-toast.
    params.delete("google")
    params.delete("reason")
    const qs = params.toString()
    window.history.replaceState(
      {},
      "",
      window.location.pathname + (qs ? `?${qs}` : ""),
    )
  }
})

const googleBusy = computed(() => googleAccount._internals.operationInFlight.value)

function handleGoogleConnect() {
  googleAccount.connect() // full-page redirect to Google consent
}

async function handleGoogleDisconnect(id: number) {
  googleMessage.value = null
  googleError.value = null
  const result = await googleAccount.disconnect(id)
  if (result.ok) {
    googleMessage.value = "Google account disconnected."
  }
}

// ---------------------------------------------------------------------------
// Todoist (feature 0020) — connect / disconnect via personal API token.
// Separate card from External Calendars (different provider, single secret).
// ---------------------------------------------------------------------------
const todoistAccount = useTodoistAccount()
const todoistForm = reactive<{ token: string }>({ token: "" })
const todoistMessage = ref<string | null>(null)

onMounted(() => {
  todoistAccount.fetchAccountStatus()
})

const isTodoistConnected = computed(() =>
  Boolean(todoistAccount.state.status?.connected),
)
const todoistBusy = computed(
  () => todoistAccount._internals.accountOperationInFlight.value !== null,
)
const todoistVerifiedAt = computed(() => {
  const ts = todoistAccount.state.status?.last_verified_at
  return ts ? new Date(ts).toLocaleString() : null
})

async function handleTodoistConnect() {
  todoistMessage.value = null
  const result = await todoistAccount.connect({ token: todoistForm.token.trim() })
  if (result.ok) {
    todoistForm.token = ""
    todoistMessage.value = "Todoist connected."
  }
}

async function handleTodoistDisconnect() {
  todoistMessage.value = null
  const result = await todoistAccount.disconnect()
  if (result.ok) {
    todoistForm.token = ""
    todoistMessage.value = "Todoist disconnected."
  }
}

// ---------------------------------------------------------------------------
// Habitica (feature 0024) — connect / disconnect via User ID + API token.
// ---------------------------------------------------------------------------
const habiticaAccount = useHabiticaAccount()
const habiticaForm = reactive<{ api_user_id: string; api_token: string }>({
  api_user_id: "",
  api_token: "",
})
const habiticaMessage = ref<string | null>(null)

onMounted(() => {
  habiticaAccount.fetchAccountStatus()
})

const isHabiticaConnected = computed(() =>
  Boolean(habiticaAccount.state.status?.connected),
)
const habiticaBusy = computed(
  () => habiticaAccount._internals.accountOperationInFlight.value !== null,
)
const habiticaVerifiedAt = computed(() => {
  const ts = habiticaAccount.state.status?.last_verified_at
  return ts ? new Date(ts).toLocaleString() : null
})
const habiticaConnectedUserId = computed(
  () => habiticaAccount.state.status?.api_user_id ?? null,
)

async function handleHabiticaConnect() {
  habiticaMessage.value = null
  const result = await habiticaAccount.connect({
    api_user_id: habiticaForm.api_user_id.trim(),
    api_token: habiticaForm.api_token.trim(),
  })
  if (result.ok) {
    habiticaForm.api_token = ""
    habiticaMessage.value = "Habitica connected."
  }
}

async function handleHabiticaDisconnect() {
  habiticaMessage.value = null
  const result = await habiticaAccount.disconnect()
  if (result.ok) {
    habiticaForm.api_user_id = ""
    habiticaForm.api_token = ""
    habiticaMessage.value = "Habitica disconnected."
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
      <SoundNotificationToggle />
    </section>

    <section class="section">
      <DesktopNotificationToggle />
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
      <h2 class="section-title">External Calendars</h2>
      <p class="section-subtitle">
        Connect calendar accounts so Day Forge can display their events
        read-only alongside your daily schedule.
      </p>

      <h3 class="subsection-title">Apple Calendar</h3>
      <p class="section-subtitle">
        Connects via iCloud CalDAV. Use an
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

      <h3 class="subsection-title">Google Calendar</h3>
      <p class="section-subtitle">
        Connects via Google sign-in. Connecting (or reconnecting) always shows
        Google's consent screen — that is expected, not an error; it guarantees
        an offline refresh token. You can connect multiple Google accounts.
      </p>

      <p v-if="googleError" class="cal-error" role="status">{{ googleError }}</p>
      <p v-else-if="googleMessage" class="cal-message" role="status">
        {{ googleMessage }}
      </p>
      <p
        v-else-if="googleAccount.state.error"
        class="cal-error"
        role="status"
      >
        {{ googleAccount.state.error }}
      </p>

      <ul
        v-if="googleAccount.state.accounts.length > 0"
        class="google-account-list"
      >
        <li
          v-for="acc in googleAccount.state.accounts"
          :key="acc.id"
          class="google-account-row"
        >
          <span class="google-account-email">{{ acc.email }}</span>
          <span
            v-if="acc.last_verified_at"
            class="google-account-verified"
          >
            verified {{ new Date(acc.last_verified_at).toLocaleDateString() }}
          </span>
          <button
            type="button"
            class="cal-disconnect"
            :disabled="googleBusy"
            @click="handleGoogleDisconnect(acc.id)"
          >
            Disconnect
          </button>
        </li>
      </ul>
      <p v-else class="cal-status">No Google accounts connected</p>

      <button
        type="button"
        class="cal-submit"
        :disabled="googleBusy"
        @click="handleGoogleConnect"
      >
        Connect Google Calendar
      </button>

      <ExternalCalendarPlacementToggle />

      <h3 class="subsection-title">Travel-time rules</h3>
      <p class="section-subtitle">
        Prefill travel minutes and category when adding an external event to
        your schedule, matched by event-title keyword.
      </p>
      <TravelRulesList :rules="localTravelRules" @changed="refreshTravelRules" />
    </section>

    <section class="section">
      <h2 class="section-title">Todoist</h2>
      <p class="section-subtitle">
        Connect your Todoist account so Day Forge can display your tasks
        read-only alongside your daily schedule.
      </p>
      <p class="section-subtitle">
        Paste a
        <a
          href="https://app.todoist.com/app/settings/integrations/developer"
          target="_blank"
          rel="noopener noreferrer"
        >personal API token</a> — Day Forge only reads your tasks, never
        writes.
      </p>

      <p v-if="isTodoistConnected" class="cal-status connected">
        Connected to Todoist<span v-if="todoistVerifiedAt">
          · verified {{ todoistVerifiedAt }}</span>
      </p>
      <p v-else class="cal-status">Not connected</p>

      <p
        v-if="todoistAccount.state.error"
        class="cal-error"
        role="status"
      >
        {{ todoistAccount.state.error }}
      </p>
      <p
        v-else-if="todoistMessage"
        class="cal-message"
        role="status"
      >
        {{ todoistMessage }}
      </p>

      <form
        v-if="!isTodoistConnected"
        class="cal-form"
        @submit.prevent="handleTodoistConnect"
      >
        <label class="cal-field">
          <span>API token</span>
          <input
            v-model="todoistForm.token"
            type="password"
            autocomplete="off"
            required
            :disabled="todoistBusy"
          />
        </label>
        <button
          type="submit"
          class="cal-submit"
          :disabled="todoistBusy"
        >
          {{ todoistBusy ? "Connecting…" : "Connect" }}
        </button>
      </form>

      <button
        v-else
        type="button"
        class="cal-disconnect"
        :disabled="todoistBusy"
        @click="handleTodoistDisconnect"
      >
        {{ todoistBusy ? "Disconnecting…" : "Disconnect" }}
      </button>
    </section>

    <section class="section">
      <h2 class="section-title">Habitica</h2>
      <p class="section-subtitle">
        Connect Habitica so Day Forge can display outstanding todos and today's
        due dailies alongside your schedule.
      </p>
      <p class="section-subtitle">
        Find your User ID and API token in
        <a
          href="https://habitica.com/user/settings/api"
          target="_blank"
          rel="noopener noreferrer"
        >Habitica API settings</a>.
      </p>

      <p v-if="isHabiticaConnected" class="cal-status connected">
        Connected to Habitica<span v-if="habiticaConnectedUserId">
          · {{ habiticaConnectedUserId }}</span><span v-if="habiticaVerifiedAt">
          · verified {{ habiticaVerifiedAt }}</span>
      </p>
      <p v-else class="cal-status">Not connected</p>

      <p
        v-if="habiticaAccount.state.error"
        class="cal-error"
        role="status"
      >
        {{ habiticaAccount.state.error }}
      </p>
      <p
        v-else-if="habiticaMessage"
        class="cal-message"
        role="status"
      >
        {{ habiticaMessage }}
      </p>

      <form
        v-if="!isHabiticaConnected"
        class="cal-form"
        @submit.prevent="handleHabiticaConnect"
      >
        <label class="cal-field">
          <span>User ID</span>
          <input
            v-model="habiticaForm.api_user_id"
            type="text"
            autocomplete="off"
            required
            :disabled="habiticaBusy"
          />
        </label>
        <label class="cal-field">
          <span>API token</span>
          <input
            v-model="habiticaForm.api_token"
            type="password"
            autocomplete="off"
            required
            :disabled="habiticaBusy"
          />
        </label>
        <button
          type="submit"
          class="cal-submit"
          :disabled="habiticaBusy"
        >
          {{ habiticaBusy ? "Connecting..." : "Connect" }}
        </button>
      </form>

      <button
        v-else
        type="button"
        class="cal-disconnect"
        :disabled="habiticaBusy"
        @click="handleHabiticaDisconnect"
      >
        {{ habiticaBusy ? "Disconnecting..." : "Disconnect" }}
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

.subsection-title {
  margin: 8px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
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

.google-account-list {
  list-style: none;
  margin: 0 0 8px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.google-account-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.google-account-email {
  font-weight: 500;
  color: var(--text-primary);
}

.google-account-verified {
  font-size: 11px;
  color: var(--text-muted);
  margin-right: auto;
}
</style>
