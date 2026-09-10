import { computed, inject, provide, ref, watch, type ComputedRef, type InjectionKey } from "vue"
import { usePage } from "@inertiajs/vue3"
import FocusIndicatorView from "../components/FocusIndicatorView.vue"
import type { TimeBlock, UserCategory } from "../types"
import { useNowMinutes } from "./useNowMinutes"
import { useFocusIndicator } from "./useFocusIndicator"
import { getCategoryColor } from "../utils/categoryColors"
import {
  activeUnfinishedBlock,
  isDayFinished,
  nextBlockAfter,
  pauseProgressRatio,
  pauseWindow,
  progressPercentFromRatio,
  progressRatio,
} from "../utils/focusIndicator"
import { remainingMinutesForBlock, timeToMinutes } from "../utils/scheduleTime"

export interface FocusIndicatorController {
  focusIndicator: ReturnType<typeof useFocusIndicator>
  indicatorActive: ComputedRef<boolean>
  indicatorPercent: ComputedRef<number>
  indicatorNextBlock: ComputedRef<TimeBlock | null>
  indicatorNextBlockTitle: ComputedRef<string | null>
  indicatorNextBlockRemaining: ComputedRef<number | null>
  indicatorPausePercent: ComputedRef<number | null>
  indicatorDayFinished: ComputedRef<boolean>
  publish: (date: string, blocks: TimeBlock[], categories?: UserCategory[]) => void
  clearSnapshot: () => void
}

export const FocusIndicatorControllerKey: InjectionKey<FocusIndicatorController> = Symbol("focusIndicatorController")

function copiedBlocks(blocks: TimeBlock[]): TimeBlock[] {
  return blocks.map((block) => ({ ...block }))
}

/** Minutes from `nowMinutes` to `hhmm`, or `null` when that is not a positive finite span. */
function minutesUntil(hhmm: string, nowMinutes: number | null): number | null {
  if (nowMinutes === null) return null
  const remaining = timeToMinutes(hhmm) - nowMinutes
  return Number.isFinite(remaining) && remaining > 0 ? remaining : null
}

export function useFocusIndicatorController(): FocusIndicatorController {
  const page = usePage()
  const retainedDate = ref("")
  const retainedBlocks = ref<TimeBlock[]>([])
  const retainedCategories = ref<UserCategory[]>([])
  const { nowMinutes, nowDate } = useNowMinutes(retainedDate)

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
  const indicatorBlockTitle = computed(() =>
    indicatorActive.value && activeBlock.value !== null ? activeBlock.value.title : null,
  )
  // The resolver the timeline itself uses, so the PiP rail can never disagree
  // with the block it mirrors — user-defined categories included.
  const indicatorCategoryColor = computed(() =>
    indicatorActive.value && activeBlock.value !== null
      ? getCategoryColor(activeBlock.value.category, undefined, retainedCategories.value)
      : null,
  )
  const indicatorNextBlock = computed(() =>
    indicatorActive.value
      ? null
      : nextBlockAfter(retainedBlocks.value, nowMinutes.value, nowDate.value),
  )
  const indicatorNextBlockTitle = computed(() => indicatorNextBlock.value?.title ?? null)
  const indicatorNextBlockRemaining = computed(() => {
    const next = indicatorNextBlock.value
    return next === null ? null : minutesUntil(next.start_time, nowMinutes.value)
  })
  const indicatorPausePercent = computed(() => {
    if (indicatorActive.value) return null
    const pause = pauseWindow(retainedBlocks.value, nowMinutes.value, nowDate.value)
    const elapsed = pauseProgressRatio(pause, nowMinutes.value)
    return elapsed === null ? null : Math.round(elapsed * 100)
  })
  const indicatorDayFinished = computed(
    () =>
      !indicatorActive.value &&
      isDayFinished(retainedBlocks.value, nowMinutes.value, nowDate.value),
  )
  const focusIndicator = useFocusIndicator({
    component: FocusIndicatorView,
    props: () => ({
      active: indicatorActive.value,
      progressPercent: indicatorPercent.value,
      blockTitle: indicatorBlockTitle.value,
      categoryColor: indicatorCategoryColor.value,
      remainingMinutes: indicatorRemaining.value,
      nextBlockTitle: indicatorNextBlockTitle.value,
      nextBlockRemainingMinutes: indicatorNextBlockRemaining.value,
      pausePercent: indicatorPausePercent.value,
      dayFinished: indicatorDayFinished.value,
      errorState: false,
    }),
  })

  function publish(date: string, blocks: TimeBlock[], categories?: UserCategory[]): void {
    retainedDate.value = date
    retainedBlocks.value = copiedBlocks(blocks)
    if (categories) retainedCategories.value = categories
  }

  function clearSnapshot(): void {
    retainedDate.value = ""
    retainedBlocks.value = []
    retainedCategories.value = []
  }

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
    indicatorPausePercent,
    indicatorDayFinished,
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
