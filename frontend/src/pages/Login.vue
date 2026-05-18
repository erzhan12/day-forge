<script setup lang="ts">
import { onMounted } from "vue"
import { useForm } from "@inertiajs/vue3"
import { applyTheme } from "../utils/theme"
import "../app.css"

defineProps<{
  errors: { non_field?: string }
}>()

// Defensive: SSR should already set data-theme="strategic" via
// `_LOGIN_TEMPLATE_DATA` in backend/schedules/views.py, but this guard
// closes the gap if a future code path renders Login without that.
onMounted(() => {
  applyTheme("strategic")
})

const form = useForm({
  username: "",
  password: "",
})

function submit() {
  form.post("/accounts/login/")
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">Day Forge</h1>
      <p class="login-subtitle">Sign in to your schedule</p>

      <div v-if="errors.non_field" class="error-banner">
        {{ errors.non_field }}
      </div>

      <form @submit.prevent="submit">
        <div class="field">
          <label for="username">Username</label>
          <input
            id="username"
            v-model="form.username"
            type="text"
            autocomplete="username"
            required
          />
        </div>
        <div class="field">
          <label for="password">Password</label>
          <input
            id="password"
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            required
          />
        </div>
        <button type="submit" class="login-btn" :disabled="form.processing">
          {{ form.processing ? "Signing in..." : "Sign in" }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}

.login-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 40px;
  width: 100%;
  max-width: 400px;
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(10px);
}

.login-title {
  font-size: 30px;
  font-weight: 700;
  text-align: center;
  color: var(--text-primary);
  margin-bottom: 4px;
  font-family: var(--font-family-display);
  letter-spacing: -0.01em;
}

.login-subtitle {
  text-align: center;
  color: var(--text-muted);
  margin-bottom: 24px;
}

.error-banner {
  background: var(--danger-surface);
  color: var(--danger-text);
  border: 1px solid var(--danger-border);
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  margin-bottom: 16px;
}

.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.field input {
  width: 100%;
  padding: 10px 12px;
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font-size: 15px;
}

.field input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.login-btn {
  width: 100%;
  padding: 12px;
  background: var(--accent);
  color: var(--accent-contrast);
  border: none;
  border-radius: var(--radius-pill);
  font-size: 15px;
  font-weight: 600;
  margin-top: 8px;
  letter-spacing: 0.01em;
}

.login-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.login-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
