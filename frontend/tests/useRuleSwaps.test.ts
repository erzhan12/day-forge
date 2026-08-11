import { beforeEach, describe, expect, it, vi } from "vitest"

const requestJsonMock = vi.fn()

vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

import { useRules } from "../src/composables/useRules"
import { useTravelRules } from "../src/composables/useTravelRules"

describe("rule swap composables", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("posts Rule ids and unwraps the rules envelope", async () => {
    const rules = [
      { id: 1, text: "First", is_active: true, priority: 0 },
      { id: 2, text: "Second", is_active: true, priority: 1 },
    ]
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { rules },
    })

    const result = await useRules().swapRules(1, 2)

    expect(requestJsonMock).toHaveBeenCalledOnce()
    expect(requestJsonMock).toHaveBeenCalledWith(
      "/api/rules/swap/",
      "POST",
      { a: 1, b: 2 },
    )
    expect(result.rules).toEqual(rules)
  })

  it("posts TravelRule ids and unwraps the travel_rules envelope", async () => {
    const travelRules = [
      {
        id: 1,
        keyword: "gym",
        travel_there_minutes: 10,
        travel_back_minutes: 10,
        category: "health",
        order: 1,
      },
      {
        id: 2,
        keyword: "office",
        travel_there_minutes: 20,
        travel_back_minutes: 20,
        category: "work",
        order: 0,
      },
    ]
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { travel_rules: travelRules },
    })

    const result = await useTravelRules().swapRules(1, 2)

    expect(requestJsonMock).toHaveBeenCalledOnce()
    expect(requestJsonMock).toHaveBeenCalledWith(
      "/api/calendar/travel-rules/swap/",
      "POST",
      { a: 1, b: 2 },
    )
    expect(result.rules).toEqual(travelRules)
  })
})
