<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue"
import { Link, router } from "@inertiajs/vue3"
import type { Rule, ScheduleSettingsWire, Template, TravelRule, UserCategory } from "../types"
import TimeZoneMismatchPrompt from "../components/TimeZoneMismatchPrompt.vue"
import SettingsCategoriesPanel from "../components/settings/SettingsCategoriesPanel.vue"
import SettingsAiAssistantPanel from "../components/settings/SettingsAiAssistantPanel.vue"
import SettingsAppearancePanel from "../components/settings/SettingsAppearancePanel.vue"
import SettingsIntegrationsPanel from "../components/settings/SettingsIntegrationsPanel.vue"
import SettingsNav from "../components/settings/SettingsNav.vue"
import SettingsNotificationsPanel from "../components/settings/SettingsNotificationsPanel.vue"
import SettingsSchedulePanel from "../components/settings/SettingsSchedulePanel.vue"
import SettingsTemplatesRulesPanel from "../components/settings/SettingsTemplatesRulesPanel.vue"
import SettingsTopicSelect from "../components/settings/SettingsTopicSelect.vue"
import { useCalendarAccount } from "../composables/useCalendarAccount"
import { useGoogleAccount } from "../composables/useGoogleAccount"
import { useHabiticaAccount } from "../composables/useHabiticaAccount"
import { useSettingsTopic } from "../composables/useSettingsTopic"
import { useTodoistAccount } from "../composables/useTodoistAccount"
// Keeps `<html data-theme>` in sync with ui_preferences across reloads.
// Required convention for every authenticated page — see RULES.md.
import { useThemeFromProps } from "../composables/useThemeFromProps"
import { todayString } from "../utils/date"
import "../app.css"

useThemeFromProps()

const props = defineProps<{
  templates: Template[]
  rules: Rule[]
  travel_rules: TravelRule[]
  categories?: UserCategory[]
  schedule_window: ScheduleSettingsWire
}>()

const { activeTopic, topics, setTopic, markKeyboardIntent } = useSettingsTopic()

const localTemplates = ref<Template[]>(props.templates.map((item) => ({ ...item })))
const localRules = ref<Rule[]>(props.rules.map((item) => ({ ...item })))
const localTravelRules = ref<TravelRule[]>(
  props.travel_rules.map((item) => ({ ...item })),
)

watch(
  () => props.templates,
  (next) => { localTemplates.value = next.map((item) => ({ ...item })) },
  { deep: true },
)
watch(
  () => props.rules,
  (next) => { localRules.value = next.map((item) => ({ ...item })) },
  { deep: true },
)
watch(
  () => props.travel_rules,
  (next) => { localTravelRules.value = next.map((item) => ({ ...item })) },
  { deep: true },
)

const weekdayTemplate = computed(
  () => localTemplates.value.find((item) => item.type === "weekday") ?? null,
)
const weekendTemplate = computed(
  () => localTemplates.value.find((item) => item.type === "weekend") ?? null,
)

function refreshTemplates(): void { router.reload({ only: ["templates"] }) }
function refreshRules(): void { router.reload({ only: ["rules"] }) }
function refreshTravelRules(): void { router.reload({ only: ["travel_rules"] }) }

const today = todayString()

// Apple Calendar (feature 0011) — connect / disconnect via CalDAV.
const calendarAccount = useCalendarAccount()
const calendarForm = reactive({ apple_id: "", password: "", base_url: "" })
const showAdvanced = ref(false)
const calendarMessage = ref<string | null>(null)

onMounted(() => { calendarAccount.fetchAccountStatus() })

const isCalendarConnected = computed(() =>
  Boolean(calendarAccount.state.status?.connected),
)
const calendarBusy = computed(
  () => calendarAccount._internals.accountOperationInFlight.value !== null,
)
const calendarDefaultBaseUrl = computed(
  () => calendarAccount.state.status?.default_base_url ?? "",
)

async function handleCalendarConnect(): Promise<void> {
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

async function handleCalendarDisconnect(): Promise<void> {
  calendarMessage.value = null
  const result = await calendarAccount.disconnect()
  if (result.ok) {
    calendarForm.apple_id = ""
    calendarForm.password = ""
    calendarForm.base_url = ""
    calendarMessage.value = "Apple Calendar disconnected."
  }
}

// Google Calendar (feature 0022) — multi-account OAuth.
const googleAccount = useGoogleAccount()
const googleMessage = ref<string | null>(null)
const googleError = ref<string | null>(null)

function googleErrorMessage(reason: string | null): string {
  switch (reason) {
    case "state": return "Session expired — sign in and connect Google again."
    case "denied": return "Google connection was cancelled."
    case "missing_code": return "Google returned an incomplete response. Try again."
    default: return "Could not connect Google Calendar. Try again."
  }
}

onMounted(() => {
  googleAccount.fetchAccounts()
  const params = new URLSearchParams(window.location.search)
  const google = params.get("google")
  if (google === "connected") {
    googleMessage.value = "Google Calendar connected."
    googleAccount.fetchAccounts()
  } else if (google === "error") {
    googleError.value = googleErrorMessage(params.get("reason"))
  }
  if (google) {
    params.delete("google")
    params.delete("reason")
    const query = params.toString()
    window.history.replaceState(
      {},
      "",
      `${window.location.pathname}${query ? `?${query}` : ""}#integrations`,
    )
    activeTopic.value = "integrations"
  }
})

const googleBusy = computed(() => googleAccount._internals.operationInFlight.value)
function handleGoogleConnect(): void { googleAccount.connect() }
async function handleGoogleDisconnect(id: number): Promise<void> {
  googleMessage.value = null
  googleError.value = null
  const result = await googleAccount.disconnect(id)
  if (result.ok) googleMessage.value = "Google account disconnected."
}

// Todoist (feature 0020) — personal API token.
const todoistAccount = useTodoistAccount()
const todoistForm = reactive({ token: "" })
const todoistMessage = ref<string | null>(null)
onMounted(() => { todoistAccount.fetchAccountStatus() })
const isTodoistConnected = computed(() =>
  Boolean(todoistAccount.state.status?.connected),
)
const todoistBusy = computed(
  () => todoistAccount._internals.accountOperationInFlight.value !== null,
)
const todoistVerifiedAt = computed(() => {
  const timestamp = todoistAccount.state.status?.last_verified_at
  return timestamp ? new Date(timestamp).toLocaleString() : null
})

async function handleTodoistConnect(): Promise<void> {
  todoistMessage.value = null
  const result = await todoistAccount.connect({ token: todoistForm.token.trim() })
  if (result.ok) {
    todoistForm.token = ""
    todoistMessage.value = "Todoist connected."
  }
}

async function handleTodoistDisconnect(): Promise<void> {
  todoistMessage.value = null
  const result = await todoistAccount.disconnect()
  if (result.ok) {
    todoistForm.token = ""
    todoistMessage.value = "Todoist disconnected."
  }
}

// Habitica (feature 0024) — User ID + API token.
const habiticaAccount = useHabiticaAccount()
const habiticaForm = reactive({ api_user_id: "", api_token: "" })
const habiticaMessage = ref<string | null>(null)
onMounted(() => { habiticaAccount.fetchAccountStatus() })
const isHabiticaConnected = computed(() =>
  Boolean(habiticaAccount.state.status?.connected),
)
const habiticaBusy = computed(
  () => habiticaAccount._internals.accountOperationInFlight.value !== null,
)
const habiticaVerifiedAt = computed(() => {
  const timestamp = habiticaAccount.state.status?.last_verified_at
  return timestamp ? new Date(timestamp).toLocaleString() : null
})
const habiticaConnectedUserId = computed(
  () => habiticaAccount.state.status?.api_user_id ?? null,
)

async function handleHabiticaConnect(): Promise<void> {
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

async function handleHabiticaDisconnect(): Promise<void> {
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
    <TimeZoneMismatchPrompt :time-zone="schedule_window.time_zone" />
    <div class="settings-shell">
      <header class="page-header">
        <Link :href="`/schedule/${today}/`" class="back-link">← Back to schedule</Link>
        <h1>Settings</h1>
      </header>

      <div class="settings-body">
        <SettingsNav
          :active-topic="activeTopic"
          :topics="topics"
          :mark-keyboard-intent="markKeyboardIntent"
        />
        <SettingsTopicSelect
          :active-topic="activeTopic"
          :topics="topics"
          :set-topic="setTopic"
        />

        <main class="settings-main">
          <div
            v-show="activeTopic === 'appearance'"
            data-settings-topic="appearance"
            :hidden="activeTopic !== 'appearance'"
            :inert="activeTopic === 'appearance' ? undefined : true"
          ><SettingsAppearancePanel /></div>
          <div
            v-show="activeTopic === 'schedule'"
            data-settings-topic="schedule"
            :hidden="activeTopic !== 'schedule'"
            :inert="activeTopic === 'schedule' ? undefined : true"
          ><SettingsSchedulePanel :window="schedule_window" /></div>
          <div
            v-show="activeTopic === 'ai-assistant'"
            data-settings-topic="ai-assistant"
            :hidden="activeTopic !== 'ai-assistant'"
            :inert="activeTopic === 'ai-assistant' ? undefined : true"
          ><SettingsAiAssistantPanel /></div>
          <div
            v-show="activeTopic === 'notifications'"
            data-settings-topic="notifications"
            :hidden="activeTopic !== 'notifications'"
            :inert="activeTopic === 'notifications' ? undefined : true"
          ><SettingsNotificationsPanel /></div>
          <div
            v-show="activeTopic === 'integrations'"
            data-settings-topic="integrations"
            :hidden="activeTopic !== 'integrations'"
            :inert="activeTopic === 'integrations' ? undefined : true"
          >
            <SettingsIntegrationsPanel
              :calendar-form="calendarForm"
              :show-advanced="showAdvanced"
              :calendar-default-base-url="calendarDefaultBaseUrl"
              :is-calendar-connected="isCalendarConnected"
              :calendar-apple-id="calendarAccount.state.status?.apple_id ?? null"
              :calendar-error="calendarAccount.state.error"
              :calendar-message="calendarMessage"
              :calendar-busy="calendarBusy"
              :handle-calendar-connect="handleCalendarConnect"
              :handle-calendar-disconnect="handleCalendarDisconnect"
              :toggle-calendar-advanced="() => { showAdvanced = !showAdvanced }"
              :google-accounts="googleAccount.state.accounts"
              :google-error="googleError"
              :google-message="googleMessage"
              :google-account-error="googleAccount.state.error"
              :google-busy="googleBusy"
              :handle-google-connect="handleGoogleConnect"
              :handle-google-disconnect="handleGoogleDisconnect"
              :todoist-form="todoistForm"
              :is-todoist-connected="isTodoistConnected"
              :todoist-verified-at="todoistVerifiedAt"
              :todoist-error="todoistAccount.state.error"
              :todoist-message="todoistMessage"
              :todoist-busy="todoistBusy"
              :handle-todoist-connect="handleTodoistConnect"
              :handle-todoist-disconnect="handleTodoistDisconnect"
              :habitica-form="habiticaForm"
              :is-habitica-connected="isHabiticaConnected"
              :habitica-verified-at="habiticaVerifiedAt"
              :habitica-connected-user-id="habiticaConnectedUserId"
              :habitica-error="habiticaAccount.state.error"
              :habitica-message="habiticaMessage"
              :habitica-busy="habiticaBusy"
              :handle-habitica-connect="handleHabiticaConnect"
              :handle-habitica-disconnect="handleHabiticaDisconnect"
            />
          </div>
          <div
            v-show="activeTopic === 'categories'"
            data-settings-topic="categories"
            :hidden="activeTopic !== 'categories'"
            :inert="activeTopic === 'categories' ? undefined : true"
          ><SettingsCategoriesPanel :categories="categories ?? []" /></div>
          <div
            v-show="activeTopic === 'templates-rules'"
            data-settings-topic="templates-rules"
            :hidden="activeTopic !== 'templates-rules'"
            :inert="activeTopic === 'templates-rules' ? undefined : true"
          >
            <SettingsTemplatesRulesPanel
              :weekday-template="weekdayTemplate"
              :weekend-template="weekendTemplate"
              :rules="localRules"
              :travel-rules="localTravelRules"
              :categories="categories"
              @saved="refreshTemplates"
              @deleted="refreshTemplates"
              @rules-changed="refreshRules"
              @travel-changed="refreshTravelRules"
            />
          </div>
        </main>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-page { padding: 24px 16px 80px; }
.settings-shell { max-width: 1040px; margin: 0 auto; }
.page-header { display: flex; flex-direction: column; gap: 8px; margin-bottom: 28px; }
.back-link { font-size: 13px; color: var(--accent); text-decoration: none; }
.back-link:hover { text-decoration: underline; }
.page-header h1 { margin: 0; font-size: 26px; color: var(--text-primary); font-family: var(--font-family-display); }
.settings-body { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
.settings-main { min-width: 0; width: 100%; max-width: 760px; }
/* scrollIntoView({ block: "start" }) honors this so the heading is not
   hidden under the sticky mobile topic <select> (top: 0, ~label+control). */
.settings-main :deep(.settings-topic-heading) {
  scroll-margin-top: 6.5rem;
}

@media (min-width: 1024px) {
  .settings-body { grid-template-columns: 224px minmax(0, 760px); gap: 32px; }
  .settings-main { grid-column: 2; }
  .settings-main :deep(.settings-topic-heading) { scroll-margin-top: 24px; }
}
</style>
