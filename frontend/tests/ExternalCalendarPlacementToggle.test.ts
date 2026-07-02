import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import ExternalCalendarPlacementToggle from "../src/components/ExternalCalendarPlacementToggle.vue"
import { clearLocalStorage } from "./helpers/storage"
import { readExternalCalendarPlacement } from "../src/utils/externalCalendarPlacementStorage"

describe("ExternalCalendarPlacementToggle", () => {
  it("defaults to sidebar and persists center on change", async () => {
    clearLocalStorage()
    const wrapper = mount(ExternalCalendarPlacementToggle)
    const center = wrapper.get('input[value="center"]')
    await center.setValue(true)
    expect(readExternalCalendarPlacement()).toBe("center")
    expect((wrapper.get('input[value="center"]').element as HTMLInputElement).checked).toBe(
      true,
    )
  })
})
