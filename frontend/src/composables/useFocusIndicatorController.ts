import { computed, provide, ref, watch, type ComputedRef, type InjectionKey } from "vue"
import { usePage } from "@inertiajs/vue3"
import FocusIndicatorView from "../components/FocusIndicatorView.vue"
import type { TimeBlock, UserCategory } from "../types"
import { useNowMinutes } from "./useNowMinutes"
import { useFocusIndicator } from "./useFocusIndicator"
import { getCategoryColor } from "../utils/categoryColors"
import { hasValidCategoryCatalog } from "../utils/categories"
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

export interface FocusIndicatorRetainedSnapshot {
  date: string
  blocks: TimeBlock[]
  categories: UserCategory[]
}

export interface FocusIndicatorController {
  focusIndicator: ReturnType<typeof useFocusIndicator>
  indicatorActive: ComputedRef<boolean>
  indicatorPercent: ComputedRef<number>
  indicatorNextBlock: ComputedRef<TimeBlock | null>
  indicatorNextBlockTitle: ComputedRef<string | null>
  indicatorNextBlockRemaining: ComputedRef<number | null>
  indicatorPausePercent: ComputedRef<number | null>
  indicatorDayFinished: ComputedRef<boolean>
  publicationGeneration: () => number
  publishIfGenerationMatches: (
    generation: number,
    date: string,
    blocks: TimeBlock[],
    categories?: UserCategory[],
    timeZone?: string,
  ) => boolean
  clearSnapshot: () => void
  retainedSnapshot: () => FocusIndicatorRetainedSnapshot
}

export const FocusIndicatorControllerKey: InjectionKey<FocusIndicatorController> = Symbol("focusIndicatorController")

function copiedBlocks(blocks: TimeBlock[]): TimeBlock[] {
  return blocks.map((block) => ({ ...block }))
}

/**
 * Snapshot categories the same way blocks are snapshotted. No caller mutates a
 * category array in place today (unlike drag previews, which is why blocks are
 * copied), so this is symmetry rather than a live fix — it just keeps the
 * retained snapshot immune to aliasing if one ever does.
 */
function copiedCategories(categories: UserCategory[]): UserCategory[] {
  return categories.map((category) => ({ ...category }))
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
  const retainedTimeZone = ref("UTC")
  const retainedBlocks = ref<TimeBlock[]>([])
  const retainedCategories = ref<UserCategory[]>([])
  let publicationGeneration = 0
  const { nowMinutes, nowDate } = useNowMinutes(retainedDate, retainedTimeZone)

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

  function sessionRefusesPublication(): boolean {
    // Mirror the definite Login / null-user clear predicates. An uninitialized
    // component is not logout and must not refuse authenticated publishers.
    if (page?.component === "Login") return true
    if (page?.props?.auth_user_id === null) return true
    return false
  }

  /** Internal write. Returns false when Login / null-user refuse the snapshot. */
  function applySnapshot(
    date: string,
    blocks: TimeBlock[],
    categories?: UserCategory[],
    timeZone?: string,
  ): boolean {
    if (sessionRefusesPublication()) return false
    if (timeZone !== undefined) retainedTimeZone.value = timeZone
    retainedDate.value = date
    retainedBlocks.value = copiedBlocks(blocks)
    // Explicit undefined check: an empty array is a real value here (it clears
    // the retained list), and only an omitted argument leaves it untouched.
    if (categories !== undefined) retainedCategories.value = copiedCategories(categories)
    return true
  }

  function clearSnapshot(): void {
    retainedDate.value = ""
    retainedTimeZone.value = "UTC"
    retainedBlocks.value = []
    retainedCategories.value = []
  }

  function retainedSnapshot(): FocusIndicatorRetainedSnapshot {
    return {
      date: retainedDate.value,
      blocks: copiedBlocks(retainedBlocks.value),
      categories: copiedCategories(retainedCategories.value),
    }
  }

  function publishIfGenerationMatches(
    generation: number,
    date: string,
    blocks: TimeBlock[],
    categories?: UserCategory[],
    timeZone?: string,
  ): boolean {
    if (generation !== publicationGeneration) return false
    return applySnapshot(date, blocks, categories, timeZone)
  }

  watch(
    () => [page?.component, page?.props?.auth_user_id] as const,
    ([component, userId], previous) => {
      const priorUserId = previous?.[1]
      const changedUser = priorUserId !== undefined && userId !== undefined && userId !== priorUserId
      if (component === "Login" || userId === null || changedUser) {
        publicationGeneration += 1
        clearSnapshot()
        focusIndicator.cleanup()
      }
    },
    { immediate: true, flush: "sync" },
  )

  // Settings (and any other authenticated page carrying a live catalogue) can
  // change category colours after Schedule has unmounted (#213). Refresh only
  // the retained catalogue, never date/blocks/time zone, and only for a valid
  // catalogue on an initialized, authenticated, non-Login page while a snapshot
  // is retained. Each guard stands alone so the session watcher above may run
  // before or after this one in the same tick.
  watch(
    () => page?.props?.categories,
    (categories) => {
      const component = page?.component
      if (typeof component !== "string" || component === "Login") return
      const userId = page?.props?.auth_user_id
      if (userId === null || userId === undefined) return
      if (retainedDate.value === "") return
      if (!hasValidCategoryCatalog(categories)) return
      retainedCategories.value = copiedCategories(categories)
    },
    { flush: "sync" },
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
    publicationGeneration: () => publicationGeneration,
    publishIfGenerationMatches,
    clearSnapshot,
    retainedSnapshot,
  }
}

export function provideFocusIndicatorController(): FocusIndicatorController {
  const controller = useFocusIndicatorController()
  provide(FocusIndicatorControllerKey, controller)
  return controller
}
