import { onBeforeUnmount, onMounted, type Ref } from "vue"

// Focus handling shared by the mobile menu and the Calendars sheet (feature
// 0113): focus moves in on mount, Tab wraps inside the container, Escape asks
// the owner to close, and focus returns to the element that opened the dialog
// (or the fallback when that element is gone) on unmount.

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export interface MobileDialogOptions {
  onClose: () => void
  /** Used when the opener was removed from the DOM before the dialog closed. */
  fallbackFocus?: () => HTMLElement | null
}

export function useMobileDialog(container: Ref<HTMLElement | null>, options: MobileDialogOptions): void {
  let opener: HTMLElement | null = null

  function focusables(): HTMLElement[] {
    return Array.from(container.value?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault()
      event.stopPropagation()
      options.onClose()
      return
    }
    if (event.key !== "Tab") return
    const items = focusables()
    if (items.length === 0) {
      event.preventDefault()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement
    if (event.shiftKey && (active === first || !container.value?.contains(active))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (active === last || !container.value?.contains(active))) {
      event.preventDefault()
      first.focus()
    }
  }

  onMounted(() => {
    const active = document.activeElement
    opener = active instanceof HTMLElement && active !== document.body ? active : null
    container.value?.addEventListener("keydown", onKeydown)
    const target = focusables()[0] ?? container.value
    target?.focus()
  })

  onBeforeUnmount(() => {
    container.value?.removeEventListener("keydown", onKeydown)
    const target = opener && opener.isConnected ? opener : options.fallbackFocus?.() ?? null
    target?.focus()
  })
}
