<script setup lang="ts">
// Title-only edit sheet of the Dark 4a phone list (feature 0113, SPEC 11.3).
// Time and category editing are issue #333. The write, Undo entry and failure
// handling match the inline rename in TimeBlock.vue.
import { computed, inject, ref } from "vue"
import type { TimeBlock } from "../types"
import { ScheduleDisabledKey, ScheduleUndoKey } from "../composables/scheduleContext"
import { useSchedule } from "../composables/useSchedule"
import { registerMutationUndo } from "../composables/useMutationUndo"
import BottomSheet from "./BottomSheet.vue"

const props = defineProps<{ block: TimeBlock; date: string }>()
const emit = defineEmits<{ close: [] }>()

const { updateBlock } = useSchedule(() => props.date)
const undo = inject(ScheduleUndoKey, undefined)
const scheduleDisabled = inject(ScheduleDisabledKey, null)
const disabled = computed(() => Boolean(scheduleDisabled?.value))

const title = ref(props.block.title)
const saving = ref(false)
const errorMessage = ref("")

async function save(): Promise<void> {
  if (saving.value || disabled.value) return
  const trimmed = title.value.trim()
  if (!trimmed || trimmed === props.block.title) {
    emit("close")
    return
  }
  saving.value = true
  errorMessage.value = ""
  const originalTitle = props.block.title
  const result = await updateBlock(props.block.id, { title: trimmed })
  saving.value = false
  if (result.ok) {
    registerMutationUndo(result, undo?.pushUndo, {
      description: `Renamed "${originalTitle}" to "${trimmed}"`,
      type: "edit",
      silent: true,
    })
    emit("close")
  } else {
    errorMessage.value = "Failed to update title"
  }
}
</script>

<template>
  <BottomSheet title="Edit block" @close="emit('close')">
    <form class="edit-form" data-testid="edit-block-form" @submit.prevent="save">
      <label class="edit-label">
        Title
        <input
          v-model="title"
          class="df-field edit-title"
          type="text"
          autocomplete="off"
          data-testid="edit-block-title"
        />
      </label>
      <p v-if="errorMessage" class="edit-error" role="alert">{{ errorMessage }}</p>
      <div class="edit-actions">
        <button type="submit" class="df-btn df-btn--primary" :disabled="saving || disabled" data-testid="edit-block-save">Save</button>
        <button type="button" class="df-btn df-btn--field" data-testid="edit-block-cancel" @click="emit('close')">Cancel</button>
      </div>
    </form>
  </BottomSheet>
</template>

<style scoped>
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .edit-form {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  html[data-theme="dark_4a"] .edit-label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    font-weight: 500;
    color: #9ca3af;
  }

  html[data-theme="dark_4a"] .edit-error {
    margin: 0;
    font-size: 13px;
    color: var(--danger-text);
  }

  html[data-theme="dark_4a"] .edit-actions {
    display: flex;
    gap: 8px;
  }

  html[data-theme="dark_4a"] .edit-actions .df-btn {
    flex: 1;
    min-height: 44px;
  }
}
</style>
