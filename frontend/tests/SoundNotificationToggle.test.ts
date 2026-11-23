// Feature 0106: the sound toggle renders the 18 px settings checkbox only in
// Dark 4a; other themes keep the native control.
import { afterEach, describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import SoundNotificationToggle from "../src/components/SoundNotificationToggle.vue"

afterEach(() => {
  delete document.documentElement.dataset.theme
  localStorage.clear()
})

describe("SoundNotificationToggle", () => {
  it("binds df-checkbox--lg only in dark_4a", () => {
    document.documentElement.dataset.theme = "dark_4a"
    const dark = mount(SoundNotificationToggle)
    const darkInput = dark.get("input[type=checkbox]")
    expect(darkInput.classes()).toEqual(expect.arrayContaining(["df-checkbox", "df-checkbox--lg"]))
    expect(darkInput.attributes("role")).toBe("switch")
    dark.unmount()

    for (const theme of ["classic", "strategic", "light_premium"]) {
      document.documentElement.dataset.theme = theme
      const other = mount(SoundNotificationToggle)
      expect(other.get("input[type=checkbox]").classes()).not.toContain("df-checkbox")
      other.unmount()
    }
  })
})
