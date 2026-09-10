import { computed, type App, type Component, createApp, getCurrentInstance, h, onUnmounted, ref } from "vue"
import { clearFocusIndicatorShouldBeOpen, readFocusIndicatorShouldBeOpen, writeFocusIndicatorShouldBeOpen } from "../utils/focusIndicatorStorage"

const PIP_WIDTH = 280
const PIP_HEIGHT = 60
// Generic, block-agnostic — never the block title. 0079 un-privated the title
// in the PiP *body*; `document.title` stays block-agnostic in every state.
const PIP_TITLE = "Focus"
const PIP_OPEN_ERROR = "Could not open indicator. Please try again."
const PIP_OPEN_ERROR_DURATION_MS = 5_000

// The PiP document is a separate Document with no app stylesheet. Inject the
// view's layout rules here rather than cloning app.css — Vue scoped CSS never
// reaches a foreign Document.
// Feature 0079: a fixed dark frame rather than the system Canvas/CanvasText
// pair, so the in-block and in-pause states read as one designed object. The
// two fonts are named with a system fallback — the app ships no webfont, and a
// PiP document must not reach out to a third-party CDN on open.
const PIP_FONT_BODY = `"Public Sans", system-ui, -apple-system, sans-serif`
const PIP_FONT_MONO = `"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace`
// No pure white, no pure black anywhere.
const PIP_INK = "#ECEAE6"
const PIP_MUTED = "#8E9299"
const PIP_SURFACE = "#17181A"
const PIP_BORDER = "#2A2D31"
const PIP_DASH = "#3A3E44"

const PIP_STYLES = `
  :root { color-scheme: dark; }
  html, body { margin: 0; width: 100%; height: 100%; background: transparent; }
  body { color: ${PIP_INK}; }
  .fi-root { width: 100%; height: 100%; flex: 1; min-width: 0; display: flex; align-items: stretch; background: ${PIP_SURFACE}; }
  .focus-indicator {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 9px;
    width: 100%;
    box-sizing: border-box;
    /* The window stays 280x60, tighter than the 320x64 mock, so the padding
       comes down from 12px/14px to keep both rows and the gap unclipped. */
    padding: 9px 11px;
    background: ${PIP_SURFACE};
    border: 1px solid ${PIP_BORDER};
    border-radius: 12px;
    font-family: ${PIP_FONT_BODY};
  }
  .fi-row--head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .fi-spacer { flex: 1; min-width: 0; }
  .fi-rail {
    flex: none;
    width: 3px;
    height: 14px;
    border-radius: 2px;
    transition: background 200ms ease, box-shadow 200ms ease;
  }
  .fi-title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    font-weight: 600;
    color: ${PIP_INK};
  }
  .fi-remaining {
    flex: none;
    font-family: ${PIP_FONT_MONO};
    font-size: 13px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: ${PIP_INK};
  }
  .fi-pause-glyph {
    flex: none;
    display: flex;
    gap: 2px;
    align-items: center;
  }
  .fi-pause-glyph i {
    display: block;
    width: 3px;
    height: 11px;
    border-radius: 1px;
    background: ${PIP_MUTED};
  }
  .fi-pause-done, .fi-arrow {
    flex: none;
    font-size: 13px;
    font-weight: 400;
    white-space: nowrap;
    color: ${PIP_MUTED};
  }
  .fi-next-title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    font-weight: 400;
    color: ${PIP_MUTED};
  }
  .fi-next-remaining {
    flex: none;
    font-family: ${PIP_FONT_MONO};
    font-size: 13px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: ${PIP_MUTED};
  }
  .fi-row--track { display: block; }
  .fi-track {
    width: 100%;
    height: 5px;
    border-radius: 3px;
    background: ${PIP_BORDER};
    overflow: hidden;
  }
  .fi-track--dashed {
    background: repeating-linear-gradient(90deg, ${PIP_DASH} 0 6px, transparent 6px 10px);
  }
  .fi-fill {
    height: 100%;
    transition: width 200ms ease, background 200ms ease;
  }
  .fi-fill--pause { background: ${PIP_MUTED}; }
  .focus-indicator[data-state="error"] {
    outline: 2px solid ${PIP_MUTED};
    outline-offset: -3px;
  }
  .fi-retry {
    flex: none;
    font-family: ${PIP_FONT_MONO};
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: ${PIP_MUTED};
  }
  .fi-neutral {
    flex: none;
    color: ${PIP_MUTED};
  }
  .fi-sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
  @media (prefers-reduced-motion: reduce) {
    .fi-fill, .fi-rail { transition: none; }
  }
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
  width?: number
  height?: number
}

/**
 * Owns the Document Picture-in-Picture window lifecycle for the focus
 * indicator: feature detection, single-instance open from a user gesture,
 * pending-request + orphan guards, a live reactive second-app mount, and
 * teardown. Its document title stays generic; the view enforces the narrow
 * active-state and idle-gap body privacy policy.
 */
export function useFocusIndicator(config: FocusIndicatorConfig) {
  const supported =
    typeof window !== "undefined" && "documentPictureInPicture" in window

  const isOpen = ref(false)
  const openError = ref<string | null>(null)
  const storedShouldBeOpen = ref(readFocusIndicatorShouldBeOpen())
  const shouldRestore = computed(() => supported && !isOpen.value && storedShouldBeOpen.value)
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
    // The PiP window is going away via browser chrome (Chrome's "Back to tab",
    // its window-close button) or a main-window reload — NOT a deliberate
    // dismissal. Preserve the device restore intent so one Show click brings it
    // back; since 0079 dropped the in-PiP X, the header Hide (via cleanup()) is
    // the only sticky explicit close that clears the intent.
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
      win.document.title = PIP_TITLE
      const style = win.document.createElement("style")
      style.textContent = PIP_STYLES
      win.document.head.appendChild(style)
      const rootEl = win.document.createElement("div")
      rootEl.className = "fi-root"
      win.document.body.appendChild(rootEl)
      // Render function re-reads config.props() each render → the shared refs it
      // dereferences are tracked, so the PiP repaints on every reactive change.
      // The view renders no control of its own (0079): dismissal is the PiP
      // chrome's own close button (non-intent, restorable) or the header Hide.
      app = createApp({ render: () => h(config.component, config.props()) })
      app.mount(rootEl)
      win.addEventListener("pagehide", onPagehide)
      isOpen.value = true
      writeFocusIndicatorShouldBeOpen(true)
      storedShouldBeOpen.value = true
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
    clearFocusIndicatorShouldBeOpen()
    storedShouldBeOpen.value = false
    teardown(true)
  }

  function dispose(): void {
    epoch++
    pendingOpen = false
    clearOpenError()
    teardown(true)
  }

  // Unmount is never an explicit user close. The root owner uses this for a
  // hard reload/unload, preserving the gesture-gated device restore intent.
  if (getCurrentInstance()) onUnmounted(dispose)

  return { supported, isOpen, openError, shouldRestore, open, cleanup, dispose }
}
