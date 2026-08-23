<script setup lang="ts">
import type { GoogleAccount } from "../../types/calendar"
import ExternalCalendarPlacementToggle from "../ExternalCalendarPlacementToggle.vue"

interface CalendarForm {
  apple_id: string
  password: string
  base_url: string
}

interface TodoistForm {
  token: string
}

interface HabiticaForm {
  api_user_id: string
  api_token: string
}

defineProps<{
  calendarForm: CalendarForm
  showAdvanced: boolean
  calendarDefaultBaseUrl: string
  isCalendarConnected: boolean
  calendarAppleId: string | null
  calendarError: string | null
  calendarMessage: string | null
  calendarBusy: boolean
  handleCalendarConnect: () => unknown
  handleCalendarDisconnect: () => unknown
  toggleCalendarAdvanced: () => void
  googleAccounts: GoogleAccount[]
  googleError: string | null
  googleMessage: string | null
  googleAccountError: string | null
  googleBusy: boolean
  handleGoogleConnect: () => unknown
  handleGoogleDisconnect: (id: number) => unknown
  todoistForm: TodoistForm
  isTodoistConnected: boolean
  todoistVerifiedAt: string | null
  todoistError: string | null
  todoistMessage: string | null
  todoistBusy: boolean
  handleTodoistConnect: () => unknown
  handleTodoistDisconnect: () => unknown
  habiticaForm: HabiticaForm
  isHabiticaConnected: boolean
  habiticaVerifiedAt: string | null
  habiticaConnectedUserId: string | null
  habiticaError: string | null
  habiticaMessage: string | null
  habiticaBusy: boolean
  handleHabiticaConnect: () => unknown
  handleHabiticaDisconnect: () => unknown
}>()
</script>

<template>
  <section class="settings-panel">
    <header class="panel-heading">
      <h2 id="settings-topic-integrations" class="settings-topic-heading" tabindex="-1">Integrations</h2>
      <p class="section-subtitle">
        Connect external services so Day Forge can show calendars, tasks, and
        habits alongside your daily schedule.
      </p>
    </header>

    <div class="integration-block" data-testid="settings-integration-apple">
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
        Connected as <strong>{{ calendarAppleId }}</strong>
      </p>
      <p v-else class="cal-status">Not connected</p>
      <p v-if="calendarError" class="cal-error" role="status">
        {{ calendarError }}
      </p>
      <p v-else-if="calendarMessage" class="cal-message" role="status">
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
          @click="toggleCalendarAdvanced"
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
        <button type="submit" class="cal-submit" :disabled="calendarBusy">
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
    </div>

    <div class="integration-block" data-testid="settings-integration-google">
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
      <p v-else-if="googleAccountError" class="cal-error" role="status">
        {{ googleAccountError }}
      </p>

      <ul v-if="googleAccounts.length > 0" class="google-account-list">
        <li v-for="account in googleAccounts" :key="account.id" class="google-account-row">
          <span class="google-account-email">{{ account.email }}</span>
          <span v-if="account.last_verified_at" class="google-account-verified">
            verified {{ new Date(account.last_verified_at).toLocaleDateString() }}
          </span>
          <button
            type="button"
            class="cal-disconnect"
            :disabled="googleBusy"
            @click="handleGoogleDisconnect(account.id)"
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
    </div>

    <div class="integration-block" data-testid="settings-integration-todoist">
      <h3 class="subsection-title">Todoist</h3>
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
        >personal API token</a> — Day Forge only reads your tasks, never writes.
      </p>
      <p v-if="isTodoistConnected" class="cal-status connected">
        Connected to Todoist<span v-if="todoistVerifiedAt">
          · verified {{ todoistVerifiedAt }}</span>
      </p>
      <p v-else class="cal-status">Not connected</p>
      <p v-if="todoistError" class="cal-error" role="status">{{ todoistError }}</p>
      <p v-else-if="todoistMessage" class="cal-message" role="status">
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
        <button type="submit" class="cal-submit" :disabled="todoistBusy">
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
    </div>

    <div class="integration-block" data-testid="settings-integration-habitica">
      <h3 class="subsection-title">Habitica</h3>
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
      <p v-if="habiticaError" class="cal-error" role="status">{{ habiticaError }}</p>
      <p v-else-if="habiticaMessage" class="cal-message" role="status">
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
        <button type="submit" class="cal-submit" :disabled="habiticaBusy">
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
    </div>
  </section>
</template>

<style scoped>
.settings-panel,
.panel-heading,
.integration-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.settings-panel { gap: 28px; }
h2 { margin: 0; color: var(--text-primary); }
h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
.subsection-title { margin: 0; font-size: 18px; color: var(--text-primary); }
.section-subtitle { margin: 0; font-size: 13px; color: var(--text-muted); }
.cal-status { margin: 0; font-size: 13px; color: var(--text-secondary); }
.cal-status.connected { color: var(--text-primary); }
.cal-error { margin: 0; padding: 8px 10px; background: var(--danger-surface); color: var(--danger-text); border-radius: 6px; font-size: 13px; }
.cal-message { margin: 0; font-size: 12px; color: var(--text-secondary); }
.cal-form { display: flex; flex-direction: column; gap: 10px; background: var(--bg-panel); border: 1px solid var(--border-strong); border-radius: 8px; padding: 12px; }
.cal-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-secondary); }
.cal-field input { font-size: 14px; padding: 6px 8px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--bg-page); color: var(--text-primary); }
.cal-advanced-toggle { align-self: flex-start; background: none; border: none; padding: 0; color: var(--accent); cursor: pointer; font-size: 12px; }
.cal-submit,
.cal-disconnect { align-self: flex-start; padding: 6px 14px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--accent); color: var(--bg-page); cursor: pointer; font-size: 13px; }
.cal-disconnect { background: var(--bg-panel); color: var(--danger-text); border-color: var(--danger-border); }
.cal-submit:disabled,
.cal-disconnect:disabled { opacity: 0.6; cursor: not-allowed; }
.google-account-list { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.google-account-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.google-account-email { font-weight: 500; color: var(--text-primary); }
.google-account-verified { font-size: 11px; color: var(--text-muted); margin-right: auto; }
</style>
