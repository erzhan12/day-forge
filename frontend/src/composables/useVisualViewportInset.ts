import { onBeforeUnmount, onMounted, ref, type Ref } from "vue"

// Height of the on-screen keyboard (or any other overlay) at the bottom of the
// layout viewport, in px (feature 0113, SPEC 11.5). iOS Safari keeps the layout
// viewport full height when the keyboard opens, so a bottom-fixed sheet must
// move up by innerHeight - visualViewport.height - visualViewport.offsetTop.
// Browsers that resize the layout viewport report 0 here.
export function useVisualViewportInset(): Ref<number> {
  const inset = ref(0)
  const vv = typeof window !== "undefined" ? window.visualViewport : null

  function update(): void {
    if (!vv) return
    inset.value = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop))
  }

  onMounted(() => {
    if (!vv) return
    update()
    vv.addEventListener("resize", update)
    vv.addEventListener("scroll", update)
  })
  onBeforeUnmount(() => {
    vv?.removeEventListener("resize", update)
    vv?.removeEventListener("scroll", update)
  })
  return inset
}
