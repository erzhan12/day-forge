<script setup lang="ts">
import { useForm } from "@inertiajs/vue3"
import "../app.css"

defineProps<{
  errors: { non_field?: string }
}>()

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
  background: #f5f5f5;
}

.login-card {
  background: white;
  border-radius: 12px;
  padding: 40px;
  width: 100%;
  max-width: 400px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.07);
}

.login-title {
  font-size: 28px;
  font-weight: 700;
  text-align: center;
  color: #111827;
  margin-bottom: 4px;
}

.login-subtitle {
  text-align: center;
  color: #6b7280;
  margin-bottom: 24px;
}

.error-banner {
  background: #fef2f2;
  color: #dc2626;
  padding: 10px 14px;
  border-radius: 6px;
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
  color: #374151;
  margin-bottom: 4px;
}

.field input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 15px;
}

.field input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.login-btn {
  width: 100%;
  padding: 12px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 15px;
  font-weight: 600;
  margin-top: 8px;
}

.login-btn:hover:not(:disabled) {
  background: #2563eb;
}

.login-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
