<script setup lang="ts">
// Dark 4a day with no template and no blocks (feature 0106): replaces the
// timeline's single long "Free" row with a title and two next steps.
import { computed } from "vue"
import { Link } from "@inertiajs/vue3"
import { emptyDayCopy } from "../utils/emptyDayCopy"

const props = defineProps<{
  date: string
  slotType: "weekday" | "weekend"
}>()

const emit = defineEmits<{ "plan-with-ai": [] }>()

const copy = computed(() => emptyDayCopy(props.date, props.slotType))
</script>

<template>
  <section class="empty-day" data-testid="empty-day-state" aria-labelledby="empty-day-title">
    <h2 id="empty-day-title" class="empty-day-title">{{ copy.title }}</h2>
    <div class="empty-day-actions">
      <Link
        href="/settings/#templates-rules"
        class="df-btn df-btn--primary"
        data-testid="empty-day-create-template"
      >{{ copy.primaryLabel }}</Link>
      <button
        type="button"
        class="df-btn df-btn--secondary"
        data-testid="empty-day-plan-with-ai"
        @click="emit('plan-with-ai')"
      >Plan with AI</button>
    </div>
  </section>
</template>

<style scoped>
.empty-day {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 16px;
  padding: 24px 20px;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
}

.empty-day-title {
  margin: 0;
  font-size: 16px;
  font-weight: 500;
  line-height: 24px;
  color: var(--text-primary);
}

.empty-day-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@container (max-width: 420px) {
  .empty-day-actions {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
  }
}
</style>
