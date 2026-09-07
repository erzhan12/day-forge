import { describe, it, expect } from "vitest"
import { mount } from "@vue/test-utils"
import Login from "../src/pages/Login.vue"

/**
 * The legal links are the only discoverable entry point to /privacy/ and
 * /terms/ from inside the app, and the Google OAuth consent screen for this
 * deployment points at those same URLs. They must stay plain anchors with a
 * full navigation — an Inertia <Link> would XHR the route and choke on the
 * Django-rendered HTML that comes back.
 */
describe("Login legal links", () => {
  function mountLogin() {
    return mount(Login, { props: { errors: {} } })
  }

  it("renders a privacy link pointing at the public route", () => {
    const link = mountLogin().get('a[href="/privacy/"]')
    expect(link.text()).toBe("Privacy Policy")
  })

  it("renders a terms link pointing at the public route", () => {
    const link = mountLogin().get('a[href="/terms/"]')
    expect(link.text()).toBe("Terms of Service")
  })

  it("uses plain anchors rather than Inertia links", () => {
    const wrapper = mountLogin()
    const anchors = wrapper.findAll(".legal-links a")
    expect(anchors).toHaveLength(2)
    for (const anchor of anchors) {
      expect(anchor.element.tagName).toBe("A")
      // Inertia's <Link> renders data-* nothing, but does intercept clicks;
      // asserting the raw href survived is the observable proxy for it.
      expect(anchor.attributes("href")).toMatch(/^\/(privacy|terms)\/$/)
    }
  })
})
