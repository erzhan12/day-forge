import { onMounted, onUnmounted, ref, type Ref } from "vue"

// 1024px matches the common `lg` breakpoint convention, but this project
// does not use Tailwind; keep the value here as the single source of truth.
export const WIDE_VIEWPORT_QUERY = "(min-width: 1024px)"

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
