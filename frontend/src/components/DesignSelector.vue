<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue"
import { router, usePage } from "@inertiajs/vue3"
import type { ThemeId } from "../types"
import { THEMES } from "../utils/themes"
import { usePreferences } from "../composables/usePreferences"
import { applyTheme, isKnownTheme, normalizeTheme } from "../utils/theme"

// Phase 5 selector. Source-of-truth rule:
//   - "Which theme is checked" reads exclusively from
//     `page.props.ui_preferences.theme` — no parallel local ref.
//   - Save flow: PATCH → router.reload({ only: ["ui_preferences"] }) →
//     useThemeFromProps's watcher fires → DOM updates. The only
//     sanctioned divergence is the reload-onError fallback below.

const { saveTheme } = usePreferences()
const page = usePage()
const isSaving = ref(false)
const pendingThemeId = ref<ThemeId | null>(null)
const errorMessage = ref<string>("")
const warningMessage = ref<string>("")
// Plain boolean (not ref()) — only read inside post-resolve callbacks
// (`router.reload` onSuccess/onError/onFinish, awaited PATCH continuation)
// to short-circuit DOM/state mutations after navigation. Reactivity would
// add overhead with no consumer; no template / computed reads this.
let isMounted = true

onBeforeUnmount(() => {
  isMounted = false
})

const currentThemeId = computed<ThemeId>(() => {
  const propTheme = page.props.ui_preferences?.theme
  if (isKnownTheme(propTheme)) return propTheme
  // Fallback: when ui_preferences is absent (e.g. a future partial reload
  // that excludes the prop), read the DOM. useThemeFromProps preserves
  // <html data-theme> across prop-absent renders, so the DOM holds the
  // last-known correct value. Reading it here keeps the selector in sync
  // with what the user actually sees, rather than defaulting to Classic.
  const domTheme =
    typeof document !== "undefined"
      ? document.documentElement.dataset.theme
      : undefined
  return normalizeTheme(domTheme)
})

function isChecked(id: ThemeId): boolean {
  return currentThemeId.value === id
}

async function selectTheme(id: ThemeId): Promise<void> {
  if (isSaving.value) return
  if (id === currentThemeId.value) return
  errorMessage.value = ""
  warningMessage.value = ""
  isSaving.value = true
  pendingThemeId.value = id
  const result = await saveTheme(id)
  if (!isMounted) return
  if (!result.ok) {
    const errors = result.errors ?? {}
    const detail =
      (errors.theme as string | undefined) ||
      (errors.body as string | undefined) ||
      (errors.detail as string | undefined) ||
      "Could not save theme. Please try again."
    errorMessage.value = detail
    isSaving.value = false
    pendingThemeId.value = null
    return
  }
  // The PATCH succeeded — refresh the `ui_preferences` prop so the
  // `useThemeFromProps` watcher fires and updates `<html data-theme>`.
  router.reload({
    only: ["ui_preferences"],
    onSuccess: () => {
      // No direct DOM work here — the watcher does it. We just clear
      // any stale warning from a previous failure. Skip if the user
      // navigated away before the reload resolved.
      if (!isMounted) return
      warningMessage.value = ""
    },
    onError: () => {
      // DB is updated but the prop didn't refresh. Apply the new theme
      // directly so the user's DOM and DB don't visibly disagree, and
      // surface a non-blocking notice.
      //
      // CRITICAL: gate on isMounted before applyTheme. If the user
      // navigated away (e.g. to /accounts/login/) before this fired,
      // applyTheme would write data-theme to the WRONG page's <html>.
      // Login is supposed to stay Strategic; a stale Light-Premium save
      // could otherwise leak its data-theme onto the login screen.
      if (!isMounted) return
      applyTheme(normalizeTheme(id))
      warningMessage.value = "Theme saved. Refresh to fully sync."
    },
    onFinish: () => {
      if (!isMounted) return
      isSaving.value = false
      pendingThemeId.value = null
    },
  })
}

function handleKeydown(event: KeyboardEvent, id: ThemeId, index: number) {
  // Arrow navigation is independent of `isSaving`. Plan §Phase 5:
  // "Keep all three cards focusable during save... Users may still want
  // to navigate between options visually to compare; they just can't
  // commit a change until save settles." Only activation keys
  // (Space/Enter) are gated on the save state.
  if (event.key === "ArrowRight" || event.key === "ArrowDown") {
    event.preventDefault()
    focusOption((index + 1) % THEMES.length)
    return
  }
  if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
    event.preventDefault()
    focusOption((index - 1 + THEMES.length) % THEMES.length)
    return
  }
  if (event.key === " " || event.key === "Enter") {
    event.preventDefault()
    if (isSaving.value) return // visible affordance only; no second PATCH
    void selectTheme(id)
  }
}

function focusOption(index: number): void {
  const target = document.querySelector<HTMLElement>(
    `[data-theme-option="${THEMES[index].id}"]`,
  )
  target?.focus()
}
</script>

<template>
  <section class="design-section" aria-labelledby="design-heading">
    <h2 id="design-heading" class="section-title">Design</h2>
    <p class="section-subtitle">
      Choose the visual style for the entire app. Changes apply immediately and
      persist across devices.
    </p>

    <div
      class="design-grid"
      role="radiogroup"
      aria-labelledby="design-heading"
    >
      <div
        v-for="(theme, index) in THEMES"
        :key="theme.id"
        :data-theme-option="theme.id"
        role="radio"
        tabindex="0"
        :aria-checked="isChecked(theme.id)"
        :aria-disabled="isSaving"
        :class="{
          'design-card': true,
          'design-card--checked': isChecked(theme.id),
          'design-card--disabled': isSaving,
          'design-card--saving': pendingThemeId === theme.id,
        }"
        @click="selectTheme(theme.id)"
        @keydown="handleKeydown($event, theme.id, index)"
      >
        <div
          class="design-card__preview"
          :style="{
            background: theme.preview.bgPage,
            color: theme.preview.textPrimary,
          }"
          aria-hidden="true"
        >
          <div
            class="design-card__preview-panel"
            :style="{
              background: theme.preview.bgPanel,
              color: theme.preview.textPrimary,
              fontFamily: theme.preview.sampleHeadingFont,
            }"
          >
            <span class="design-card__sample-heading">
              {{ theme.preview.sampleHeading }}
            </span>
            <span
              class="design-card__sample-accent"
              :style="{ background: theme.preview.accent }"
            />
          </div>
        </div>

        <div class="design-card__body">
          <div class="design-card__title-row">
            <span class="design-card__title">{{ theme.label }}</span>
            <span
              v-if="isChecked(theme.id)"
              class="design-card__checkmark"
              aria-hidden="true"
              >✓</span
            >
            <span
              v-else-if="pendingThemeId === theme.id"
              class="design-card__spinner"
              aria-hidden="true"
            />
          </div>
          <p class="design-card__description">{{ theme.description }}</p>
        </div>
      </div>
    </div>

    <p
      v-if="errorMessage"
      class="design-feedback design-feedback--error"
      role="status"
      aria-live="polite"
    >
      {{ errorMessage }}
    </p>
    <p
      v-if="warningMessage"
      class="design-feedback design-feedback--warning"
      role="status"
      aria-live="polite"
    >
      {{ warningMessage }}
    </p>
  </section>
</template>

<style scoped>
.design-section {
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

.design-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: 1fr;
  margin-top: 4px;
}

@media (min-width: 720px) {
  .design-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

.design-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color 120ms ease, box-shadow 120ms ease, transform 80ms ease;
  outline: none;
}

.design-card:hover {
  border-color: var(--border-strong);
}

.design-card:focus-visible {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.design-card--checked {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent) inset;
}

.design-card--disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.design-card--saving {
  opacity: 0.9;
}

.design-card__preview {
  border-radius: var(--radius-sm);
  padding: 14px;
  min-height: 100px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.design-card__preview-panel {
  border-radius: var(--radius-sm);
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.design-card__sample-heading {
  font-size: 14px;
  font-weight: 600;
  flex: 1;
}

.design-card__sample-accent {
  width: 28px;
  height: 4px;
  border-radius: var(--radius-pill);
}

.design-card__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.design-card__title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.design-card__title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  flex: 1;
}

.design-card__checkmark {
  color: var(--accent);
  font-size: 16px;
  font-weight: 700;
}

.design-card__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: design-spin 0.7s linear infinite;
}

@keyframes design-spin {
  to {
    transform: rotate(360deg);
  }
}

.design-card__description {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.design-feedback {
  margin: 4px 0 0;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
}

.design-feedback--error {
  background: var(--danger-surface);
  color: var(--danger-text);
  border: 1px solid var(--danger-border);
}

.design-feedback--warning {
  background: var(--warning-surface);
  color: var(--warning-text);
  border: 1px solid var(--warning-border);
}
</style>
