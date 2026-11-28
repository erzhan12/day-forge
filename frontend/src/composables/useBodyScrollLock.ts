import { onBeforeUnmount, onMounted } from "vue"

// Page scroll lock for the mobile sheets and menu (feature 0113). Locks are
// counted, so a sheet opened over another keeps the page fixed until the last
// one closes; the prior inline overflow values are restored then.
let locks = 0
let saved: { html: string; body: string } | null = null

function lock(): void {
  if (locks === 0) {
    saved = { html: document.documentElement.style.overflow, body: document.body.style.overflow }
    document.documentElement.style.overflow = "hidden"
    document.body.style.overflow = "hidden"
  }
  locks += 1
}

function unlock(): void {
  if (locks === 0) return
  locks -= 1
  if (locks === 0 && saved) {
    document.documentElement.style.overflow = saved.html
    document.body.style.overflow = saved.body
    saved = null
  }
}

export function useBodyScrollLock(): void {
  let held = false
  onMounted(() => { lock(); held = true })
  onBeforeUnmount(() => { if (held) { held = false; unlock() } })
}
