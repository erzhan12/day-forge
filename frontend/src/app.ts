import { createApp, h, type DefineComponent } from "vue"
import { createInertiaApp } from "@inertiajs/vue3"

import { applyTheme, isKnownTheme } from "./utils/theme"

// Boot-time theme guard. The base.html template server-renders
// `<html data-theme="…">` before any JS runs, so the DOM should already
// be correct. We only repair the attribute if it is missing or
// unrecognized — never overwrite an SSR-correct value, which would
// reintroduce the Classic-light flash this feature is designed to remove.
const initialTheme = document.documentElement.dataset.theme
if (!isKnownTheme(initialTheme)) {
  applyTheme("classic")
}

createInertiaApp({
  resolve: (name: string) => {
    const pages = import.meta.glob<{ default: DefineComponent }>(
      "./pages/**/*.vue",
      { eager: true },
    )
    const page = pages[`./pages/${name}.vue`]
    if (!page) {
      throw new Error(`Page not found: ${name}`)
    }
    return page
  },
  setup({ el, App, props, plugin }) {
    createApp({ render: () => h(App, props) })
      .use(plugin)
      .mount(el)
  },
})
