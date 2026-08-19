import { afterEach, describe, expect, it, vi } from "vitest"
import { flushPromises } from "@vue/test-utils"
import { defineComponent, h, nextTick, ref } from "vue"
import { useFocusIndicator } from "../src/composables/useFocusIndicator"

// A minimal component that renders aria-valuenow from a prop, so we can prove
// the PiP view stays reactive after open.
const Probe = defineComponent({
  props: { value: { type: Number, required: true } },
  render() {
    return h("div", { role: "progressbar", "aria-valuenow": String(this.value) })
  },
})

function makeFakeWindow() {
  const doc = document.implementation.createHTMLDocument("")
  const listeners: Record<string, Array<() => void>> = {}
  return {
    document: doc,
    closed: false,
    addEventListener: (t: string, hnd: () => void) => {
      ;(listeners[t] ||= []).push(hnd)
    },
    removeEventListener: (t: string, hnd: () => void) => {
      listeners[t] = (listeners[t] || []).filter((x) => x !== hnd)
    },
    close: vi.fn(function (this: { closed: boolean }) {
      this.closed = true
    }),
    _emit: (t: string) => (listeners[t] || []).forEach((hnd) => hnd()),
  }
}

function installFakePip(win?: ReturnType<typeof makeFakeWindow>) {
  const requestWindow = vi.fn().mockResolvedValue(win ?? makeFakeWindow())
  ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
    requestWindow,
    window: null,
  }
  return requestWindow
}

afterEach(() => {
  delete (window as unknown as { documentPictureInPicture?: unknown }).documentPictureInPicture
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe("useFocusIndicator", () => {
  it("reports supported=false and open() is a non-throwing no-op when the API is absent", async () => {
    delete (window as unknown as { documentPictureInPicture?: unknown }).documentPictureInPicture
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    expect(fi.supported).toBe(false)
    await expect(fi.open()).resolves.toBeUndefined()
    expect(fi.isOpen.value).toBe(false)
  })

  it("open() creates exactly one window; a second call while pending does not re-request", async () => {
    const requestWindow = installFakePip()
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    const p1 = fi.open()
    const p2 = fi.open() // still pending → must be a no-op
    await Promise.all([p1, p2])
    await flushPromises()
    expect(requestWindow).toHaveBeenCalledTimes(1)
    expect(fi.isOpen.value).toBe(true)
  })

  it("open() is a no-op when the window is already open", async () => {
    const requestWindow = installFakePip()
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    await fi.open()
    await flushPromises()
    expect(fi.isOpen.value).toBe(true)
    await fi.open() // already open → must not re-request
    await flushPromises()
    expect(requestWindow).toHaveBeenCalledTimes(1)
  })

  it("surfaces a generic error when the PiP request is rejected", async () => {
    const requestWindow = installFakePip()
    requestWindow.mockRejectedValueOnce(
      new DOMException("User activation is required", "NotAllowedError"),
    )
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })

    await fi.open()

    expect(fi.isOpen.value).toBe(false)
    expect(fi.openError.value).toBe("Could not open indicator. Please try again.")
    // Release the 5s auto-dismiss timer so it does not outlive the test.
    fi.cleanup()
  })

  it("dismisses the open error after a brief interval", async () => {
    vi.useFakeTimers()
    const requestWindow = installFakePip()
    requestWindow.mockRejectedValueOnce(
      new DOMException("User activation is required", "NotAllowedError"),
    )
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    await fi.open()
    expect(fi.openError.value).not.toBeNull()

    vi.advanceTimersByTime(5_000)

    expect(fi.openError.value).toBeNull()
  })

  it("clears the previous error when retrying and successfully reopens", async () => {
    const requestWindow = installFakePip()
    requestWindow.mockRejectedValueOnce(
      new DOMException("User activation is required", "NotAllowedError"),
    )
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    await fi.open()
    expect(fi.openError.value).not.toBeNull()

    requestWindow.mockResolvedValueOnce(makeFakeWindow())
    await fi.open()
    await flushPromises()

    expect(fi.openError.value).toBeNull()
    expect(fi.isOpen.value).toBe(true)
    expect(requestWindow).toHaveBeenCalledTimes(2)
  })

  it("sets a generic PiP document.title (never a block title)", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    await fi.open()
    await flushPromises()
    expect(win.document.title).toBe("Focus")
    expect(win.document.title).not.toContain("Block")
  })

  it("keeps the PiP view live: aria-valuenow updates when the reactive source changes", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    const value = ref(10)
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: value.value }) })
    await fi.open()
    await flushPromises()
    const bar = () => win.document.querySelector('[role="progressbar"]')
    expect(bar()?.getAttribute("aria-valuenow")).toBe("10")
    value.value = 55
    await nextTick()
    expect(bar()?.getAttribute("aria-valuenow")).toBe("55")
  })

  it("manual PiP close (pagehide) resets isOpen and allows reopening", async () => {
    const win = makeFakeWindow()
    const requestWindow = installFakePip(win)
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    await fi.open()
    await flushPromises()
    expect(fi.isOpen.value).toBe(true)
    win._emit("pagehide")
    await nextTick()
    expect(fi.isOpen.value).toBe(false)
    // Reopen allowed (new fake window under the same requestWindow mock).
    requestWindow.mockResolvedValueOnce(makeFakeWindow())
    await fi.open()
    await flushPromises()
    expect(fi.isOpen.value).toBe(true)
    expect(requestWindow).toHaveBeenCalledTimes(2)
  })

  it("cleanup() closes the window and detaches", async () => {
    const win = makeFakeWindow()
    installFakePip(win)
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    await fi.open()
    await flushPromises()
    fi.cleanup()
    expect(win.close).toHaveBeenCalled()
    expect(fi.isOpen.value).toBe(false)
  })

  it("allows reopening after cleanup() (distinct epoch path from pagehide)", async () => {
    const requestWindow = installFakePip(makeFakeWindow())
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    await fi.open()
    await flushPromises()
    expect(fi.isOpen.value).toBe(true)
    fi.cleanup()
    expect(fi.isOpen.value).toBe(false)
    requestWindow.mockResolvedValueOnce(makeFakeWindow())
    await fi.open()
    await flushPromises()
    expect(fi.isOpen.value).toBe(true)
    expect(requestWindow).toHaveBeenCalledTimes(2)
  })

  it("cleanup() while the request is still pending closes the orphaned window on resolve", async () => {
    let resolveWin: ((w: unknown) => void) | null = null
    const win = makeFakeWindow()
    const requestWindow = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveWin = resolve
        }),
    )
    ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
      requestWindow,
      window: null,
    }
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })
    const p = fi.open()
    fi.cleanup() // dispose before the request resolves
    resolveWin!(win)
    await p
    await flushPromises()
    expect(win.close).toHaveBeenCalled()
    expect(fi.isOpen.value).toBe(false)
  })

  it("a stale rejection after cleanup()+reopen leaves the new window and shows no error", async () => {
    // #1 stays pending so we can reject it *after* a newer request has adopted
    // its own window — the epoch-race the catch guard must survive.
    let rejectFirst: ((e: unknown) => void) | null = null
    const secondWin = makeFakeWindow()
    const requestWindow = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectFirst = reject
          }),
      )
      .mockResolvedValueOnce(secondWin)
    ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
      requestWindow,
      window: null,
    }
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })

    const p1 = fi.open() // #1 pending
    fi.cleanup() // epoch++ → #1 is now superseded
    await fi.open() // #2 resolves and adopts secondWin
    await flushPromises()
    expect(fi.isOpen.value).toBe(true)

    // #1 rejects late: must NOT tear down #2's live window, reset its guard, or
    // surface a (no-longer-actionable) error.
    rejectFirst!(new DOMException("User activation is required", "NotAllowedError"))
    await p1
    await flushPromises()

    expect(secondWin.close).not.toHaveBeenCalled()
    expect(fi.isOpen.value).toBe(true)
    expect(fi.openError.value).toBeNull()

    fi.cleanup()
  })

  it("a stale resolution does not clobber a newer pending request's in-flight guard", async () => {
    // #1 and #2 both stay pending so we can resolve #1 *late* while #2 is still
    // in flight (isOpen === false) — the success-path analogue of the epoch race.
    let resolveFirst: ((w: unknown) => void) | null = null
    let resolveSecond: ((w: unknown) => void) | null = null
    const firstWin = makeFakeWindow()
    const requestWindow = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSecond = resolve
          }),
      )
    ;(window as unknown as { documentPictureInPicture: unknown }).documentPictureInPicture = {
      requestWindow,
      window: null,
    }
    const fi = useFocusIndicator({ component: Probe, props: () => ({ value: 0 }) })

    const p1 = fi.open() // #1 pending
    fi.cleanup() // epoch++ → #1 superseded
    const p2 = fi.open() // #2 pending, isOpen still false

    // #1 resolves late: it must close its orphan and must NOT reset the shared
    // `pendingOpen` that #2 now owns.
    resolveFirst!(firstWin)
    await p1
    await flushPromises()
    expect(firstWin.close).toHaveBeenCalled()

    // A third open() while #2 is in flight must still be a no-op.
    fi.open()
    expect(requestWindow).toHaveBeenCalledTimes(2)

    // Let #2 finish cleanly.
    resolveSecond!(makeFakeWindow())
    await p2
    await flushPromises()
    expect(fi.isOpen.value).toBe(true)

    fi.cleanup()
  })
})
