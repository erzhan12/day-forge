<script setup lang="ts">
import type { Rule, Template, TravelRule, UserCategory } from "../../types"
import RulesList from "../RulesList.vue"
import TemplateEditor from "../TemplateEditor.vue"
import TravelRulesList from "../TravelRulesList.vue"

defineProps<{
  weekdayTemplate: Template | null
  weekendTemplate: Template | null
  rules: Rule[]
  travelRules: TravelRule[]
  categories?: UserCategory[]
}>()

const emit = defineEmits<{
  (event: "saved"): void
  (event: "deleted"): void
  (event: "rules-changed"): void
  (event: "travel-changed"): void
}>()
</script>

<template>
  <section class="settings-panel">
    <h2 id="settings-topic-templates-rules" class="settings-topic-heading" tabindex="-1">
      Templates &amp; Rules
    </h2>

    <div class="section">
      <h3 class="subsection-title">Templates</h3>
      <p class="section-subtitle">
        One template per day type. The active template is the baseline for
        each new day's auto-generated draft.
      </p>
      <div class="template-grid">
        <TemplateEditor
          :template="weekdayTemplate"
          slot-type="weekday"
          :categories="categories"
          @saved="emit('saved')"
          @deleted="emit('deleted')"
        />
        <TemplateEditor
          :template="weekendTemplate"
          slot-type="weekend"
          :categories="categories"
          @saved="emit('saved')"
          @deleted="emit('deleted')"
        />
      </div>
    </div>

    <div class="section">
      <h3 class="subsection-title">Rules</h3>
      <p class="section-subtitle">
        Active rules are passed to the AI when generating drafts. Higher
        priority rules take precedence on conflict. When you ask chat to add a
        block without a time, the backend places it at the nearest free slot
        forward from now — a 25-minute default duration, 10-minute gaps around
        neighbours, aligned to 5 minutes.
      </p>
      <RulesList :rules="rules" @changed="emit('rules-changed')" />
    </div>

    <div class="section">
      <h3 class="subsection-title">Travel-time rules</h3>
      <p class="section-subtitle">
        Prefill travel minutes and category when adding an external event to
        your schedule, matched by title keyword or source calendar name.
        Keyword rules always take precedence over calendar-only rules.
      </p>
      <TravelRulesList :rules="travelRules" :categories="categories" @changed="emit('travel-changed')" />
    </div>
  </section>
</template>

<style scoped>
.settings-panel,
.section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.settings-panel {
  gap: 28px;
}

h2 {
  margin: 0;
  color: var(--text-primary);
}

h2:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}

.subsection-title {
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
</style>
