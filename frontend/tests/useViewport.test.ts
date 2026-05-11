// Direct coverage for useViewport. The composable has subscription /
// unsubscription logic against a MediaQueryList — high-level Schedule
// tests would only catch a binary "matches" mistake, not a leaked
// listener or an off-by-one breakpoint. See 0008_PLAN.md Phase 5.5.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, h, nextTick } from "vue"
import { mount, VueWrapper } from "@vue/test-utils"
import { clearLocalStorage } from "./helpers/storage"
import { useViewport, WIDE_VIEWPORT_QUERY } from "../src/composables/useViewport"

type ChangeHandler = (e: { matches: boolean }) => void

interface MqlMock {
  matches: boolean
  media: string
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
  handlers: ChangeHandler[]
  fire: (matches: boolean) => void
}

function makeMql(matches: boolean): MqlMock {
  const handlers: ChangeHandler[] = []
  return {
    matches,
    media: WIDE_VIEWPORT_QUERY,
    handlers,
    addEventListener: vi.fn((_event: string, h: ChangeHandler) => {
      handlers.push(h)
    }),
    removeEventListener: vi.fn((_event: string, h: ChangeHandler) => {
      const i = handlers.indexOf(h)
      if (i >= 0) handlers.splice(i, 1)
    }),
    fire(matches: boolean) {
      this.matches = matches
      for (const h of [...handlers]) h({ matches })
    },
  }
}

let activeMql: MqlMock | null = null

function stubMatchMedia(mql: MqlMock): void {
  activeMql = mql
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation(() => mql),
  )
}

const Probe = defineComponent({
  setup() {
    const { isWide } = useViewport()
    return () => h("div", { "data-testid": "probe" }, String(isWide.value))
  },
})

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  activeMql = null
  clearLocalStorage()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("useViewport", () => {
  it("initial isWide mirrors matchMedia(WIDE_VIEWPORT_QUERY).matches — wide", () => {
    stubMatchMedia(makeMql(true))
    wrapper = mount(Probe)
    expect(wrapper.find('[data-testid="probe"]').text()).toBe("true")
  })

  it("initial isWide mirrors matchMedia(WIDE_VIEWPORT_QUERY).matches — narrow", () => {
    stubMatchMedia(makeMql(false))
    wrapper = mount(Probe)
    expect(wrapper.find('[data-testid="probe"]').text()).toBe("false")
  })

  it("reacts to matchMedia change events", async () => {
    const mql = makeMql(false)
    stubMatchMedia(mql)
    wrapper = mount(Probe)
    expect(wrapper.find('[data-testid="probe"]').text()).toBe("false")
    mql.fire(true)
    await nextTick()
    expect(wrapper.find('[data-testid="probe"]').text()).toBe("true")
  })

  it("removes the change listener on unmount (no leak)", () => {
    const mql = makeMql(true)
    stubMatchMedia(mql)
    wrapper = mount(Probe)
    expect(mql.addEventListener).toHaveBeenCalledTimes(1)
    expect(mql.handlers.length).toBe(1)
    wrapper.unmount()
    wrapper = null
    expect(mql.removeEventListener).toHaveBeenCalledTimes(1)
    expect(mql.handlers.length).toBe(0)
  })

  it("queries `(min-width: 1024px)` exactly — breakpoint constant pinned", () => {
    stubMatchMedia(makeMql(true))
    wrapper = mount(Probe)
    expect(WIDE_VIEWPORT_QUERY).toBe("(min-width: 1024px)")
    expect((window.matchMedia as unknown as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
      "(min-width: 1024px)",
    )
  })

  it("treats the 1024px breakpoint as inclusive", () => {
    function mountAtWidth(width: number): VueWrapper {
      stubMatchMedia(makeMql(width >= 1024))
      return mount(Probe)
    }

    wrapper = mountAtWidth(1024)
    expect(wrapper.find('[data-testid="probe"]').text()).toBe("true")
    wrapper.unmount()

    wrapper = mountAtWidth(1023)
    expect(wrapper.find('[data-testid="probe"]').text()).toBe("false")
  })
})
