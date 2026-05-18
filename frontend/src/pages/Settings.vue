<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { Link, router } from "@inertiajs/vue3"
import type { Rule, Template } from "../types"
import TemplateEditor from "../components/TemplateEditor.vue"
import RulesList from "../components/RulesList.vue"
import DesignSelector from "../components/DesignSelector.vue"
import { todayString } from "../utils/date"
// Keeps `<html data-theme>` in sync with ui_preferences across reloads.
// Required convention for every authenticated page — see RULES.md.
import { useThemeFromProps } from "../composables/useThemeFromProps"
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
</style>
