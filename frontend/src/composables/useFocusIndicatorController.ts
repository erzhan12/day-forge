import { computed, inject, provide, ref, watch, type ComputedRef, type InjectionKey } from "vue"
import { usePage } from "@inertiajs/vue3"
import FocusIndicatorView from "../components/FocusIndicatorView.vue"
import type { TimeBlock } from "../types"
import { useNowMinutes } from "./useNowMinutes"
import { useFocusIndicator } from "./useFocusIndicator"
import {
  activeUnfinishedBlock,
  nextBlockAfter,
  progressPercentFromRatio,
  progressRatio,
} from "../utils/focusIndicator"
import { remainingMinutesForBlock, timeToMinutes } from "../utils/scheduleTime"
import {
  FOCUS_INDICATOR_OPACITY_DEFAULT,
  normalizeFocusIndicatorOpacity,
} from "../utils/focusIndicatorOpacity"

export interface FocusIndicatorController {
  focusIndicator: ReturnType<typeof useFocusIndicator>
  indicatorActive: ComputedRef<boolean>
  indicatorPercent: ComputedRef<number>
  indicatorNextBlock: ComputedRef<TimeBlock | null>
  indicatorNextBlockTitle: ComputedRef<string | null>
  indicatorNextBlockRemaining: ComputedRef<number | null>
  publish: (date: string, blocks: TimeBlock[]) => void
  clearSnapshot: () => void
}

export const FocusIndicatorControllerKey: InjectionKey<FocusIndicatorController> = Symbol("focusIndicatorController")

function copiedBlocks(blocks: TimeBlock[]): TimeBlock[] {
  return blocks.map((block) => ({ ...block }))
}

export function useFocusIndicatorController(): FocusIndicatorController {
  const page = usePage()
  const retainedDate = ref("")
  const retainedBlocks = ref<TimeBlock[]>([])
  const { nowMinutes, nowDate } = useNowMinutes(retainedDate)
  // Seed from the account prop so the initial useFocusIndicator() below is
  // constructed with the correct opacity from the start — rather than relying on
  // the immediate watch to patch a default snapshot before the first open().
  const opacity = ref(
    normalizeFocusIndicatorOpacity(
      page?.props?.ui_preferences?.focus_indicator_opacity ?? FOCUS_INDICATOR_OPACITY_DEFAULT,
    ),
  )

  const activeBlock = computed(() =>
    activeUnfinishedBlock(retainedBlocks.value, nowMinutes.value, nowDate.value),
  )
  const ratio = computed(() =>
    activeBlock.value === null || nowMinutes.value === null
      ? null
      : progressRatio(activeBlock.value, nowMinutes.value),
  )
  const indicatorActive = computed(() => ratio.value !== null)
  const indicatorPercent = computed(() => progressPercentFromRatio(ratio.value))
  const indicatorRemaining = computed(() =>
    activeBlock.value === null || nowMinutes.value === null
      ? null
      : remainingMinutesForBlock(activeBlock.value, nowMinutes.value),
  )
  const indicatorNextBlock = computed(() =>
    indicatorActive.value
      ? null
      : nextBlockAfter(retainedBlocks.value, nowMinutes.value, nowDate.value),
  )
  const indicatorNextBlockTitle = computed(() => indicatorNextBlock.value?.title ?? null)
  const indicatorNextBlockRemaining = computed(() => {
    const next = indicatorNextBlock.value
    if (next === null || nowMinutes.value === null) return null
    const remaining = timeToMinutes(next.start_time) - nowMinutes.value
    return Number.isFinite(remaining) && remaining > 0 ? remaining : null
  })
  const focusIndicator = useFocusIndicator({
    component: FocusIndicatorView,
    opacity: opacity.value,
    props: () => ({
      active: indicatorActive.value,
      progressPercent: indicatorPercent.value,
      remainingMinutes: indicatorRemaining.value,
      nextBlockTitle: indicatorNextBlockTitle.value,
      nextBlockRemainingMinutes: indicatorNextBlockRemaining.value,
      errorState: false,
    }),
  })

  function publish(date: string, blocks: TimeBlock[]): void {
    retainedDate.value = date
    retainedBlocks.value = copiedBlocks(blocks)
  }

  function clearSnapshot(): void {
    retainedDate.value = ""
    retainedBlocks.value = []
  }

  watch(
    () => page?.props?.ui_preferences?.focus_indicator_opacity,
    (value) => {
      // Prop absence is a partial-response boundary: retain the last valid
      // account value instead of resetting an open PiP to the default.
      if (value === undefined) return
      opacity.value = normalizeFocusIndicatorOpacity(value)
      focusIndicator.setOpacity(opacity.value)
    },
    { immediate: true },
  )
  watch(
    () => page?.component,
    (component) => {
      // Only a definite Login component is unauthenticated. No prop-presence
      // inference: authenticated responses deliberately have no user marker.
      if (component === "Login") {
        clearSnapshot()
        focusIndicator.cleanup()
      }
    },
    { immediate: true },
  )

  return {
    focusIndicator,
    indicatorActive,
    indicatorPercent,
    indicatorNextBlock,
    indicatorNextBlockTitle,
    indicatorNextBlockRemaining,
    publish,
    clearSnapshot,
  }
}

export function provideFocusIndicatorController(): FocusIndicatorController {
  const controller = useFocusIndicatorController()
  provide(FocusIndicatorControllerKey, controller)
  return controller
}

export function useProvidedFocusIndicatorController(): FocusIndicatorController | null {
  return inject(FocusIndicatorControllerKey, null)
}
