import { onMounted, onUnmounted, ref, type Ref } from "vue"

// 1024px matches the common `lg` breakpoint convention, but this project
// does not use Tailwind; keep the value here as the single source of truth.
export const WIDE_VIEWPORT_QUERY = "(min-width: 1024px)"

// Mobile layout breakpoint (feature 0113, SPEC section 11): at most 640 px.
// Kept separate from useViewport so isWide and its single listener stay as
// they were; the mobile layout also requires the Dark 4a theme, which the
// caller combines with this flag.
export const MOBILE_VIEWPORT_QUERY = "(max-width: 640px)"

export function useViewport(): { isWide: Ref<boolean> } {
  const mql = window.matchMedia(WIDE_VIEWPORT_QUERY)
  const isWide = ref<boolean>(mql.matches)

  function onChange(e: MediaQueryListEvent): void {
    isWide.value = e.matches
  }

  onMounted(() => {
    mql.addEventListener("change", onChange)
  })

  onUnmounted(() => {
    mql.removeEventListener("change", onChange)
  })

  return { isWide }
}

export function useIsMobile(): { isMobile: Ref<boolean> } {
  const mql = window.matchMedia(MOBILE_VIEWPORT_QUERY)
  const isMobile = ref<boolean>(mql.matches)

  function onChange(e: MediaQueryListEvent): void {
    isMobile.value = e.matches
  }

  onMounted(() => {
    mql.addEventListener("change", onChange)
  })

  onUnmounted(() => {
    mql.removeEventListener("change", onChange)
  })

  return { isMobile }
}
