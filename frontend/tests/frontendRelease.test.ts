import { afterEach, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

afterEach(() => {
  document.querySelector('meta[name="frontend-version"]')?.remove()
  vi.unstubAllGlobals()
  vi.resetModules()
})

it("keeps the running bundle identity after history/page state changes", async () => {
  const meta = document.createElement("meta")
  meta.name = "frontend-version"
  meta.content = "release-a"
  document.head.append(meta)
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => "{}" })
  vi.stubGlobal("fetch", fetch)
  const { requestJson } = await import("../src/composables/useHttp")
  await requestJson("/api/rules/", "GET")
  meta.content = "release-b"
  await requestJson("/api/rules/", "POST", { text: "Work" })
  expect(fetch.mock.calls.map(([, options]) => options.headers["X-Frontend-Version"])).toEqual(["release-a", "release-a"])
})

it("shows an explicit reload notice for a release rejection without replaying the write", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: false, status: 409, text: async () => JSON.stringify({
    code: "frontend_outdated", errors: { detail: "Reload to continue." },
  }) })
  vi.stubGlobal("fetch", fetch)
  const { requestJson } = await import("../src/composables/useHttp")
  const Notice = (await import("../src/components/FrontendReleaseNotice.vue")).default
  const wrapper = mount(Notice)
  try {
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(await requestJson("/api/blocks/1/", "PATCH", { title: "Changed" })).toMatchObject({
      ok: false, status: 409, code: "frontend_outdated",
    })
    expect(fetch).toHaveBeenCalledOnce()
    expect(wrapper.get('[role="alert"]').text()).toContain("Unsent text")
    expect(wrapper.get("button").text()).toBe("Reload")
  } finally { wrapper.unmount() }
})

it("does not mistake an ordinary revision conflict for a new release", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 409, text: async () => JSON.stringify({ code: "schedule_changed" }) }))
  const { requestJson } = await import("../src/composables/useHttp")
  const { useFrontendRelease } = await import("../src/composables/useFrontendRelease")
  await requestJson("/api/blocks/1/", "PATCH", {})
  expect(useFrontendRelease().outdated.value).toBe(false)
})
