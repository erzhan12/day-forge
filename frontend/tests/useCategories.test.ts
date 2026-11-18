import { beforeEach, describe, expect, it, vi } from "vitest"

const { reload } = vi.hoisted(() => ({ reload: vi.fn() }))

vi.mock("@inertiajs/vue3", () => ({
  router: { reload },
}))

import { useCategories } from "../src/composables/useCategories"

beforeEach(() => {
  reload.mockReset()
})

describe("useCategories", () => {
  it("requests auth_user_id with the categories refresh", () => {
    useCategories().refresh()

    expect(reload).toHaveBeenCalledTimes(1)
    expect(reload.mock.calls[0][0].only).toEqual(["categories", "auth_user_id"])
  })

  it("requests auth_user_id with the post-delete refresh", () => {
    useCategories().refresh(true)

    expect(reload).toHaveBeenCalledTimes(1)
    expect(reload.mock.calls[0][0].only).toEqual(["categories", "templates", "travel_rules", "auth_user_id"])
  })
})
