<script setup lang="ts">
import { computed } from "vue"
import { useAI } from "../composables/useAI"
import { useDraft } from "../composables/useDraft"

const props = defineProps<{
  hasTemplate: boolean
  slotType: "weekday" | "weekend"
}>()

const emit = defineEmits<{
  (e: "click"): void
}>()

const { isProcessing, apiHealthy } = useAI()
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
  border: 1px solid #fcd34d;
  border-radius: 12px;
  background: #fef3c7;
  color: #92400e;
  cursor: pointer;
  font-weight: 500;
}

.regen-btn:hover:not(:disabled) {
  background: #fde68a;
}

.regen-btn.disabled,
.regen-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.reason {
  margin: 0;
  font-size: 11px;
  color: #92400e;
}
</style>
