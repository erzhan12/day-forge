// DailyExportTokenPanel — self-contained Settings panel for the personal
// daily-export credential. Mocks the HTTP layer (not the composable) so the
// real generation-gating/dispose logic in useDailyExportToken is exercised
// end-to-end through the mounted component.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

type Deferred<T> = {
  promise: Promise<T>
  resolve: (v: T) => void
}

function defer<T>(): Deferred<T> {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

const requestJsonMock = vi.fn()

vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

import DailyExportTokenPanel from "../src/components/settings/DailyExportTokenPanel.vue"

function mountPanel(authUserId: number | null = 7) {
  return mount(DailyExportTokenPanel, { props: { authUserId } })
}

describe("DailyExportTokenPanel", () => {
  beforeEach(() => requestJsonMock.mockReset())
  afterEach(() => vi.restoreAllMocks())

  it("shows a loading state before the status request resolves", async () => {
    const deferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(deferred.promise)
    const wrapper = mountPanel()
    expect(wrapper.get('[data-testid="export-token-status"]').text()).toBe("Loading…")
    deferred.resolve({ ok: true, data: { has_token: false, created_at: null } })
    await flushPromises()
  })

  it("shows the absent state with a Create button", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true, data: { has_token: false, created_at: null },
    })
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.get('[data-testid="export-token-status"]').text()).toBe("No token yet.")
    expect(wrapper.find('[data-testid="export-token-create"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="export-token-revoke"]').exists()).toBe(false)
  })

  it("shows the active state with a Revoke button", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true, data: { has_token: true, created_at: "2026-08-29T09:00:00+00:00" },
    })
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.get('[data-testid="export-token-status"]').text()).toContain(
      "Active since",
    )
    expect(wrapper.find('[data-testid="export-token-revoke"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="export-token-create"]').exists()).toBe(false)
  })

  it("creates a token, reveals it once, and lets the user dismiss it", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: false, created_at: null } })
      .mockResolvedValueOnce({
        ok: true,
        data: { token: "dfx_secret123", has_token: true, created_at: "2026-08-29T09:00:00+00:00" },
      })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="export-token-create"]').trigger("click")
    await flushPromises()

    expect(requestJsonMock).toHaveBeenLastCalledWith(
      "/api/user/export-token/", "POST", undefined, { expectedUserId: 7 },
    )
    const reveal = wrapper.get('[data-testid="export-token-reveal"]')
    expect(reveal.text()).toContain("Shown once")
    expect(wrapper.get<HTMLInputElement>('[data-testid="export-token-value"]').element.value).toBe(
      "dfx_secret123",
    )

    await wrapper.get('[data-testid="export-token-dismiss"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-testid="export-token-reveal"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="export-token-revoke"]').exists()).toBe(true)
  })

  it("revokes an active token and returns to the Create state", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: true, created_at: "now" } })
      .mockResolvedValueOnce({ ok: true })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="export-token-revoke"]').trigger("click")
    await flushPromises()

    expect(requestJsonMock).toHaveBeenLastCalledWith(
      "/api/user/export-token/", "DELETE", undefined, { expectedUserId: 7 },
    )
    expect(wrapper.get('[data-testid="export-token-create"]').exists()).toBe(true)
  })

  it("surfaces a creation error", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: false, created_at: null } })
      .mockResolvedValueOnce({ ok: false, status: 400, errors: { detail: "Nope." } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="export-token-create"]').trigger("click")
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe("Nope.")
  })

  it("surfaces the token_exists conflict and refreshes to the active state", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: false, created_at: null } })
      .mockResolvedValueOnce({
        ok: false, status: 409, code: "token_exists", errors: { detail: "Exists." },
      })
      .mockResolvedValueOnce({ ok: true, data: { has_token: true, created_at: "now" } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="export-token-create"]').trigger("click")
    await flushPromises()

    // The refreshed status (now active) supersedes the transient conflict
    // error — the Revoke button alone communicates the current state.
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="export-token-revoke"]').exists()).toBe(true)
  })

  it("an uncertain (network-failure) creation response refreshes rather than assumes failure", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: false, created_at: null } })
      .mockResolvedValueOnce({
        ok: false, errors: { detail: "Network error. Please check your connection." },
      })
      .mockResolvedValueOnce({ ok: true, data: { has_token: true, created_at: "now" } })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.get('[data-testid="export-token-create"]').trigger("click")
    await flushPromises()

    expect(requestJsonMock).toHaveBeenCalledTimes(3)
    expect(wrapper.get('[data-testid="export-token-revoke"]').exists()).toBe(true)
  })

  it("prevents a duplicate click from firing a second create request", async () => {
    const createDeferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: false, created_at: null } })
      .mockReturnValueOnce(createDeferred.promise)
    const wrapper = mountPanel()
    await flushPromises()

    const button = wrapper.get<HTMLButtonElement>('[data-testid="export-token-create"]')
    await button.trigger("click")
    await button.trigger("click")
    expect(requestJsonMock).toHaveBeenCalledTimes(2) // initial status GET + exactly one POST
    expect(button.element.disabled).toBe(true)

    createDeferred.resolve({ ok: true, data: { token: "dfx_x", created_at: "now" } })
    await flushPromises()
  })

  it("a late status response cannot publish a credential after unmount", async () => {
    const statusDeferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(statusDeferred.promise)
    const wrapper = mountPanel()

    wrapper.unmount()
    statusDeferred.resolve({ ok: true, data: { has_token: true, created_at: "now" } })
    await flushPromises()
    // No assertion target exists once unmounted; reaching here without a
    // thrown error (e.g. a write to a torn-down reactive target) is the point.
  })

  it("remounting never restores a previously revealed raw value", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: false, created_at: null } })
      .mockResolvedValueOnce({
        ok: true, data: { token: "dfx_secret", has_token: true, created_at: "now" },
      })
    const first = mountPanel()
    await flushPromises()
    await first.get('[data-testid="export-token-create"]').trigger("click")
    await flushPromises()
    expect(first.find('[data-testid="export-token-reveal"]').exists()).toBe(true)
    first.unmount()

    requestJsonMock.mockResolvedValueOnce({
      ok: true, data: { has_token: true, created_at: "now" },
    })
    const second = mountPanel()
    await flushPromises()
    expect(second.find('[data-testid="export-token-reveal"]').exists()).toBe(false)
    expect(second.get('[data-testid="export-token-revoke"]').exists()).toBe(true)
  })

  it("an account change (remount under a new key) never carries the raw value forward", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { has_token: false, created_at: null } })
      .mockResolvedValueOnce({
        ok: true, data: { token: "dfx_owner_a", has_token: true, created_at: "now" },
      })
    const ownerA = mountPanel(1)
    await flushPromises()
    await ownerA.get('[data-testid="export-token-create"]').trigger("click")
    await flushPromises()
    expect(ownerA.find('[data-testid="export-token-reveal"]').exists()).toBe(true)
    ownerA.unmount() // Simulates Settings.vue's `:key="authUserId"` teardown.

    requestJsonMock.mockResolvedValueOnce({
      ok: true, data: { has_token: false, created_at: null },
    })
    const ownerB = mountPanel(2)
    await flushPromises()
    expect(ownerB.find('[data-testid="export-token-reveal"]').exists()).toBe(false)
  })
})
