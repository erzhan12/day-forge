import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { reactive } from "vue"
import { FocusIndicatorControllerKey } from "../src/composables/useFocusIndicatorController"

const state = vi.hoisted(() => ({
  page: null as unknown,
  saveFocusIndicatorOpacity: vi.fn(),
  reload: vi.fn(),
}))
vi.mock("@inertiajs/vue3", () => ({
  usePage: () => state.page,
  router: { reload: (...args: unknown[]) => state.reload(...args) },
}))
vi.mock("../src/composables/usePreferences", () => ({
  usePreferences: () => ({
    saveFocusIndicatorOpacity: (...args: unknown[]) => state.saveFocusIndicatorOpacity(...args),
  }),
}))
import SettingsAppearancePanel from "../src/components/settings/SettingsAppearancePanel.vue"

const page = reactive({ props: { ui_preferences: { theme: "classic", focus_indicator_opacity: 0.42 } } })
state.page = page
const saveFocusIndicatorOpacity = state.saveFocusIndicatorOpacity
const reload = state.reload

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const setOpacity = vi.fn()
const open = vi.fn()
const requestWindow = vi.fn()
const cleanup = vi.fn()
let wrapper: VueWrapper | null = null

function mountPanel() {
  wrapper = mount(SettingsAppearancePanel, {
    global: {
      provide: {
        [FocusIndicatorControllerKey as symbol]: {
          focusIndicator: { setOpacity, open, requestWindow, cleanup },
        },
      },
    },
  })
  return wrapper
}

beforeEach(() => {
  page.props.ui_preferences.focus_indicator_opacity = 0.42
  saveFocusIndicatorOpacity.mockReset().mockResolvedValue({ ok: true })
  reload.mockReset().mockImplementation((options) => {
    options.onSuccess?.()
    options.onFinish?.()
  })
  setOpacity.mockClear()
  open.mockClear()
  requestWindow.mockClear()
  cleanup.mockClear()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe("SettingsAppearancePanel opacity", () => {
  it("renders an account-backed accessible percent range", () => {
    const w = mountPanel()
    const input = w.get('input[type="range"]')
    expect(input.attributes("min")).toBe("0.2")
    expect(input.attributes("max")).toBe("1")
    expect(input.attributes("step")).toBe("0.01")
    expect(w.text()).toContain("42%")
  })

  it("commits the decimal range value", async () => {
    const w = mountPanel()
    await w.get('input[type="range"]').setValue("0.55")
    expect(saveFocusIndicatorOpacity).toHaveBeenCalledWith(0.55)
  })

  it("keeps one PATCH in flight and sends exactly one trailing commit with the latest value", async () => {
    const first = deferred<{ ok: true }>()
    const second = deferred<{ ok: true }>()
    saveFocusIndicatorOpacity
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    reload.mockImplementation((options) => {
      options.onSuccess?.()
      options.onFinish?.()
    })
    const w = mountPanel()
    const input = w.get('input[type="range"]')

    await input.setValue("0.50")
    await input.setValue("0.61")
    await input.setValue("0.73")
    expect(saveFocusIndicatorOpacity).toHaveBeenCalledTimes(1)
    expect(saveFocusIndicatorOpacity).toHaveBeenLastCalledWith(0.5)

    first.resolve({ ok: true })
    await flushPromises()
    expect(saveFocusIndicatorOpacity).toHaveBeenCalledTimes(2)
    expect(saveFocusIndicatorOpacity).toHaveBeenLastCalledWith(0.73)

    second.resolve({ ok: true })
    await flushPromises()
    expect(saveFocusIndicatorOpacity).toHaveBeenCalledTimes(2)
    expect((input.element as HTMLInputElement).value).toBe("0.73")
    expect(setOpacity).toHaveBeenLastCalledWith(0.73)
  })

  it("does not let a slow reload stomp a slider move made after its PATCH was sent", async () => {
    const save = deferred<{ ok: true }>()
    saveFocusIndicatorOpacity.mockReturnValueOnce(save.promise)
    reload.mockImplementation(() => {})
    const w = mountPanel()
    const input = w.get('input[type="range"]')
    await input.setValue("0.50")
    await input.setValue("0.68")

    save.resolve({ ok: true })
    await flushPromises()
    const options = reload.mock.calls[0][0]
    page.props.ui_preferences.focus_indicator_opacity = 0.5
    options.onSuccess()
    await flushPromises()

    expect((input.element as HTMLInputElement).value).toBe("0.68")
    expect(setOpacity).toHaveBeenLastCalledWith(0.68)
  })

  it("rolls back a failed PATCH to the committed value and leaves a newer preview intact", async () => {
    const first = deferred<{ ok: false, errors: { focus_indicator_opacity: string } }>()
    const second = deferred<{ ok: false, errors: { focus_indicator_opacity: string } }>()
    const trailing = deferred<{ ok: true }>()
    saveFocusIndicatorOpacity
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockReturnValueOnce(trailing.promise)
    const w = mountPanel()
    const input = w.get('input[type="range"]')

    await input.setValue("0.50")
    first.resolve({ ok: false, errors: { focus_indicator_opacity: "Try again" } })
    await flushPromises()
    expect((input.element as HTMLInputElement).value).toBe("0.42")
    expect(setOpacity).toHaveBeenLastCalledWith(0.42)
    expect(w.get('[role="alert"]').text()).toBe("Try again")

    await input.setValue("0.55")
    await input.setValue("0.66")
    second.resolve({ ok: false, errors: { focus_indicator_opacity: "Try again" } })
    await flushPromises()
    expect((input.element as HTMLInputElement).value).toBe("0.66")
    expect(setOpacity).toHaveBeenLastCalledWith(0.66)
  })

  it("keeps a successfully saved preview on reload failure and warns without rollback", async () => {
    reload.mockImplementation((options) => {
      options.onError?.()
      options.onFinish?.()
    })
    const w = mountPanel()
    const input = w.get('input[type="range"]')

    await input.setValue("0.58")
    await flushPromises()

    expect((input.element as HTMLInputElement).value).toBe("0.58")
    expect(setOpacity).toHaveBeenLastCalledWith(0.58)
    expect(w.get('[role="status"]').text()).toContain("Opacity saved")
  })

  it("reconciles a newer cross-session prop once no commit is in flight", async () => {
    const w = mountPanel()
    const input = w.get('input[type="range"]')
    await input.setValue("0.50")
    await flushPromises()
    expect((input.element as HTMLInputElement).value).toBe("0.5")

    // Another session's newer value arrives via Inertia while idle (not in-flight).
    page.props.ui_preferences.focus_indicator_opacity = 0.9
    await flushPromises()
    expect((input.element as HTMLInputElement).value).toBe("0.9")
    expect(setOpacity).toHaveBeenLastCalledWith(0.9)
  })

  it("clears a stale save error once a queued commit succeeds", async () => {
    const firstFail = deferred<{ ok: false, errors: { focus_indicator_opacity: string } }>()
    const trailingOk = deferred<{ ok: true }>()
    saveFocusIndicatorOpacity
      .mockReturnValueOnce(firstFail.promise)
      .mockReturnValueOnce(trailingOk.promise)
    reload.mockImplementation((options) => { options.onSuccess?.(); options.onFinish?.() })
    const w = mountPanel()
    const input = w.get('input[type="range"]')

    await input.setValue("0.50")
    await input.setValue("0.66")
    firstFail.resolve({ ok: false, errors: { focus_indicator_opacity: "Try again" } })
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)

    trailingOk.resolve({ ok: true })
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it("suppresses a superseded commit's reload-failure warning after a newer slider move", async () => {
    const aPatch = deferred<{ ok: true }>()
    const bPatch = deferred<{ ok: true }>()
    saveFocusIndicatorOpacity
      .mockReturnValueOnce(aPatch.promise)
      .mockReturnValueOnce(bPatch.promise)
    reload.mockImplementation((options) => { options.onError?.(); options.onFinish?.() })
    const w = mountPanel()
    const input = w.get('input[type="range"]')

    await input.setValue("0.50")   // commit A in flight (generation 1)
    await input.setValue("0.66")   // generation 2, B queued

    aPatch.resolve({ ok: true })   // A's reload fails, but A is now superseded (gen 2 != 1)
    await flushPromises()
    // No stale "Opacity saved" warning from the superseded commit while B is in flight.
    expect(w.find('[role="status"]').exists()).toBe(false)

    bPatch.resolve({ ok: true })   // B's reload fails for the CURRENT value → legit warning
    await flushPromises()
    expect(w.find('[role="status"]').exists()).toBe(true)
  })

  it("recovers and keeps committing when a save promise rejects", async () => {
    saveFocusIndicatorOpacity
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue({ ok: true })
    reload.mockImplementation((options) => { options.onSuccess?.(); options.onFinish?.() })
    const w = mountPanel()
    const input = w.get('input[type="range"]')

    await input.setValue("0.50")
    await flushPromises()
    expect(w.get('[role="alert"]').text()).toContain("Could not save")

    // inFlight must have been released — a later input still commits (not stuck).
    await input.setValue("0.66")
    await flushPromises()
    expect(saveFocusIndicatorOpacity).toHaveBeenLastCalledWith(0.66)
  })

  it("does not fire a queued commit when a reload settles after unmount", async () => {
    let finishReload: () => void = () => {}
    reload.mockImplementation((options) => {
      options.onSuccess?.()
      finishReload = () => options.onFinish?.()
    })
    const w = mountPanel()
    const input = w.get('input[type="range"]')

    await input.setValue("0.50")
    await input.setValue("0.66")
    await flushPromises()
    expect(saveFocusIndicatorOpacity).toHaveBeenCalledTimes(1)

    w.unmount()
    wrapper = null
    finishReload()
    await flushPromises()
    expect(saveFocusIndicatorOpacity).toHaveBeenCalledTimes(1)
  })

  it("previews input synchronously in an injected open PiP without opening or closing it", async () => {
    const pending = deferred<{ ok: true }>()
    saveFocusIndicatorOpacity.mockReturnValueOnce(pending.promise)
    const w = mountPanel()

    await w.get('input[type="range"]').setValue("0.64")

    expect(setOpacity).toHaveBeenLastCalledWith(0.64)
    expect(open).not.toHaveBeenCalled()
    expect(requestWindow).not.toHaveBeenCalled()
    expect(cleanup).not.toHaveBeenCalled()
  })
})
