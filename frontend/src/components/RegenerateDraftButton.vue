<script setup lang="ts">
import { computed } from "vue"
import { useChat } from "../composables/useChat"
import { useDraft } from "../composables/useDraft"

const props = defineProps<{
  hasTemplate: boolean
  slotType: "weekday" | "weekend"
}>()

const emit = defineEmits<{
  (e: "click"): void
}>()

const { isProcessing, apiHealthy } = useChat()
const { isGeneratingDraft } = useDraft()

const disabled = computed(
  () =>
    !props.hasTemplate ||
    isGeneratingDraft.value ||
    isProcessing.value ||
    !apiHealthy.value,
)

const slotLabel = computed(() =>
  props.slotType === "weekday" ? "weekday" : "weekend",
)

function handleClick() {
  if (disabled.value) return
  emit("click")
}
</script>

<template>
  <div class="regen">
    <button
      type="button"
      class="regen-btn"
      :class="{ disabled }"
      :disabled="disabled"
      @click="handleClick"
    >
      {{ isGeneratingDraft ? "Generating..." : "Regenerate draft" }}
    </button>
    <p v-if="!hasTemplate" class="reason">
      No {{ slotLabel }} template configured.
    </p>
  </div>
</template>

<style scoped>
.regen {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.regen-btn {
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--warning-border);
  border-radius: 12px;
  background: var(--warning-surface);
  color: var(--warning-text);
  cursor: pointer;
  font-weight: 500;
}

.regen-btn:hover:not(:disabled) {
  /* Slightly stronger than the resting surface; uses the border token
     which is a more saturated step in the same warning family. */
  background: var(--warning-border);
}

.regen-btn.disabled,
.regen-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.reason {
  margin: 0;
  font-size: 11px;
  color: var(--warning-text);
}
</style>
