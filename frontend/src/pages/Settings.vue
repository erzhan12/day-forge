<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { Link, router } from "@inertiajs/vue3"
import type { Rule, Template } from "../types"
import TemplateEditor from "../components/TemplateEditor.vue"
import RulesList from "../components/RulesList.vue"
import { todayString } from "../utils/date"
import "../app.css"

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
  max-width: 720px;
  margin: 0 auto;
  padding: 24px 16px 80px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.page-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.back-link {
  font-size: 13px;
  color: #3b82f6;
  text-decoration: none;
}

.back-link:hover {
  text-decoration: underline;
}

.page-header h1 {
  margin: 0;
  font-size: 24px;
  color: #111827;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  margin: 0;
  font-size: 18px;
  color: #111827;
}

.section-subtitle {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
}

.template-grid {
  display: grid;
  gap: 16px;
}

@media (min-width: 720px) {
  .template-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
