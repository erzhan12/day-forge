import { type App, type Component, createApp, getCurrentInstance, h, onUnmounted, ref } from "vue"

const PIP_WIDTH = 240
const PIP_HEIGHT = 60
// Generic, block-agnostic — never the block title (privacy invariant).
const PIP_TITLE = "Focus"
const PIP_OPEN_ERROR = "Could not open indicator. Please try again."
const PIP_OPEN_ERROR_DURATION_MS = 5_000

// The PiP document is a separate Document with no app stylesheet; give it its
// own minimal scoped styles rather than cloning the whole app CSS.
const PIP_STYLES = `
  :root { color-scheme: light dark; }
  html, body { margin: 0; height: 100%; }
  body { display: flex; align-items: center; }
`

interface FocusIndicatorConfig {
  /** The component rendered inside the PiP window (Slice 4's view). */
  component: Component
  /**
   * Fresh prop object for the component, read on every render. MUST read each
   * reactive ref's `.value` inside so the render effect tracks it and the PiP
   * repaints live (see 0049 plan § reactive-bridge).
   */
  props: () => Record<string, unknown>
  title?: string
  width?: number
  height?: number
}

/**
 * Owns the Document Picture-in-Picture window lifecycle for the focus
 * indicator: feature detection, single-instance open from a user gesture,
 * pending-request + orphan guards, a live reactive second-app mount, and
 * teardown. Contains NO block fields.
 */
export function useFocusIndicator(config: FocusIndicatorConfig) {
  const supported =
    typeof window !== "undefined" && "documentPictureInPicture" in window

  const isOpen = ref(false)
  const openError = ref<string | null>(null)
  let pipWindow: Window | null = null
  let app: App | null = null
  let pendingOpen = false
  let openErrorTimer: ReturnType<typeof setTimeout> | null = null
  // Bumped by cleanup()/dispose so a request that resolves after teardown
  // closes its just-created window instead of adopting an orphan.
  let epoch = 0

  function clearOpenError(): void {
    if (openErrorTimer !== null) {
      clearTimeout(openErrorTimer)
      openErrorTimer = null
    }
    openError.value = null
  }

  function showOpenError(): void {
    clearOpenError()
    openError.value = PIP_OPEN_ERROR
    openErrorTimer = setTimeout(() => {
      openError.value = null
      openErrorTimer = null
    }, PIP_OPEN_ERROR_DURATION_MS)
  }

  function teardown(closeWindow: boolean): void {
    if (app) {
      app.unmount()
      app = null
    }
    if (pipWindow) {
      pipWindow.removeEventListener("pagehide", onPagehide)
      if (closeWindow) pipWindow.close()
      pipWindow = null
    }
    isOpen.value = false
  }

  function onPagehide(): void {
    // The window is already going away; just release our side.
    teardown(false)
  }

  async function open(): Promise<void> {
    if (!supported) return
    // Single-instance + rapid-double-click guard: ignore if already open or a
    // request is still in flight.
    if (isOpen.value || pendingOpen) return
    clearOpenError()
    pendingOpen = true
    const myEpoch = epoch
    try {
      const win = await window.documentPictureInPicture!.requestWindow({
        width: config.width ?? PIP_WIDTH,
        height: config.height ?? PIP_HEIGHT,
      })
      // cleanup()/a newer open() fired while we were pending — do not adopt and
      // do NOT reset the shared `pendingOpen`, which the newer request now owns
      // (resetting it would let a third open() slip past the in-flight guard and
      // spawn a duplicate window); just close this orphan. Symmetric to the
      // epoch guard on the catch path below.
      if (myEpoch !== epoch) {
        win.close()
        return
      }
      pendingOpen = false
      pipWindow = win
      win.document.title = config.title ?? PIP_TITLE
      const style = win.document.createElement("style")
      style.textContent = PIP_STYLES
      win.document.head.appendChild(style)
      const rootEl = win.document.createElement("div")
      win.document.body.appendChild(rootEl)
      // Render function re-reads config.props() each render → the shared refs it
      // dereferences are tracked, so the PiP repaints on every reactive change.
      app = createApp({ render: () => h(config.component, config.props()) })
      app.mount(rootEl)
      win.addEventListener("pagehide", onPagehide)
      isOpen.value = true
    } catch (err) {
      // Any mid-setup failure (rejected requestWindow, or a throw after
      // `pipWindow = win` but before `isOpen`) must close the partially-opened
      // orphan and clear refs — otherwise a later open() would spawn a second,
      // untracked PiP window. Guard the whole recovery on the epoch, mirroring
      // the success path above: if cleanup()/a newer open() bumped `epoch` while
      // we were pending, this stale rejection no longer owns the state — running
      // teardown() would close the *newer* window and resetting the shared
      // `pendingOpen` would clobber the newer request's in-flight guard. A
      // superseded request is also no longer user-actionable, so no error shows.
      if (myEpoch === epoch) {
        pendingOpen = false
        teardown(true)
        // Every surfaced failure gets the same block-agnostic recovery message;
        // detailed diagnostics remain confined to the console below.
        showOpenError()
      }
      // Console policy (independent of the user-facing alert above):
      // NotAllowedError (no transient activation) is the expected failure and
      // stays out of the console. Surface everything else — non-DOMExceptions
      // (programming errors) and other DOMException subtypes — for post-mortem
      // diagnosis, even for a superseded request (a genuine bug is worth a log).
      if (!(err instanceof DOMException)) {
        console.error("[useFocusIndicator] unexpected error during PiP setup:", err)
      } else if (err.name !== "NotAllowedError") {
        console.error("[useFocusIndicator] PiP setup DOMException:", err.name)
      }
    }
  }

  function cleanup(): void {
    // Invalidate any in-flight request so its resolve closes the orphan window.
    epoch++
    pendingOpen = false
    clearOpenError()
    teardown(true)
  }

  if (getCurrentInstance()) onUnmounted(cleanup)

  return { supported, isOpen, openError, open, cleanup }
}
