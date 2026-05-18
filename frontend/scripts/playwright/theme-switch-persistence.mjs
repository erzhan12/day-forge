// Feature 0010 — design templates persistence and FOUC-prevention check.
//
// Verifies:
//   (a) User-observable persistence: a saved theme survives reload AND
//       a log-out / log-in cycle. The selector's checked state and the
//       <html data-theme> attribute agree after each step.
//   (b) Server-rendered first paint (no FOUC): blocking the JS bundle
//       still leaves the correct data-theme attribute on <html> because
//       the value comes from base.html's `template_data`, not from JS.
//       The test fails CLOSED — if the route interception misses, JS
//       hydrates and applyTheme() would silently "correct" any wrong
//       value, masking a regression. We assert that at least one
//       app-entry request was actually aborted before reading the DOM.
//
// Run from frontend/:
//   node scripts/playwright/theme-switch-persistence.mjs
//
// Pre-reqs: Django :8006, Vite :5173, playwright user. No LLM key needed.
// ⚠️  LOCAL DEVELOPMENT ONLY. The preflight reset wipes the user's
// preferences row.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const REPO_ROOT = resolve(process.cwd(), "..")

function shellExec(script) {
  execSync(`uv run python backend/manage.py shell -c "${script}"`, {
    stdio: "inherit",
    cwd: REPO_ROOT,
  })
}

console.log("→ Preflight: resetting playwright user's theme to classic…")
try {
  shellExec(`
from templates_mgr.models import UserPreferences
from django.contrib.auth.models import User
u = User.objects.get(username='${USERNAME}')
prefs, _ = UserPreferences.objects.get_or_create(user=u, defaults={'theme': 'classic'})
prefs.theme = 'classic'
prefs.save(update_fields=['theme'])
print('reset theme to classic for', u.username)
`)
} catch (err) {
  console.error("\n❌ Preflight reset failed.")
  console.error(err.message)
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
let exitCode = 0
try {
  const context = await browser.newContext()
  const page = await context.newPage()

  // -- Step 1: log in -----------------------------------------------------
  console.log("→ Logging in…")
  await page.goto(`${BASE}/accounts/login/`)
  await page.fill('input[name="username"]', USERNAME)
  await page.fill('input[name="password"]', PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])

  // -- Step 2: visit Settings, assert Classic checked ---------------------
  console.log("→ Visiting Settings, expecting Classic checked…")
  await page.goto(`${BASE}/settings/`)
  await page.waitForSelector('[data-theme-option="classic"]')
  let checked = await page.getAttribute(
    '[data-theme-option="classic"]',
    "aria-checked",
  )
  if (checked !== "true") {
    throw new Error(`Expected Classic checked, got aria-checked=${JSON.stringify(checked)}`)
  }

  // -- Step 3: click Strategic, wait for PATCH + reload to settle ---------
  console.log("→ Selecting Strategic…")
  const patchPromise = page.waitForResponse((resp) =>
    resp.url().includes("/api/user/preferences/") && resp.request().method() === "PATCH",
  )
  await page.click('[data-theme-option="strategic"]')
  const patchResp = await patchPromise
  if (patchResp.status() !== 200) {
    throw new Error(`PATCH did not return 200 — got ${patchResp.status()}`)
  }
  // The reload-driven update should update <html data-theme> shortly.
  await page.waitForFunction(
    () => document.documentElement.dataset.theme === "strategic",
    null,
    { timeout: 5000 },
  )

  // -- Step 4: reload, confirm strategic is still applied -----------------
  console.log("→ Reloading, expecting strategic to persist…")
  await page.reload()
  await page.waitForSelector('[data-theme-option="strategic"]')
  const themeAfterReload = await page.getAttribute("html", "data-theme")
  if (themeAfterReload !== "strategic") {
    throw new Error(
      `After reload data-theme=${JSON.stringify(themeAfterReload)}, want 'strategic'`,
    )
  }

  // -- Step 5: log out, assert login page is strategic --------------------
  console.log("→ Logging out, expecting login to remain strategic…")
  await page.evaluate(async () => {
    const tokenMatch = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
    const token = tokenMatch ? decodeURIComponent(tokenMatch[1]) : ""
    await fetch("/accounts/logout/", {
      method: "POST",
      headers: { "X-XSRF-TOKEN": token },
    })
  })
  await page.goto(`${BASE}/accounts/login/`)
  const loginTheme = await page.getAttribute("html", "data-theme")
  if (loginTheme !== "strategic") {
    throw new Error(`login page data-theme=${JSON.stringify(loginTheme)}, want 'strategic'`)
  }

  // -- Step 6: log back in, confirm strategic is still selected -----------
  console.log("→ Logging in again, expecting strategic still selected…")
  await page.fill('input[name="username"]', USERNAME)
  await page.fill('input[name="password"]', PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])
  await page.goto(`${BASE}/settings/`)
  await page.waitForSelector('[data-theme-option="strategic"]')
  checked = await page.getAttribute(
    '[data-theme-option="strategic"]',
    "aria-checked",
  )
  if (checked !== "true") {
    throw new Error(
      `After re-login Strategic aria-checked=${JSON.stringify(checked)}, want 'true'`,
    )
  }

  // -- Step 7: JS-blocked FOUC check (fails CLOSED) -----------------------
  // Block the app entry bundle so JS does not hydrate. The <html data-theme>
  // we observe must come from base.html's `template_data`.
  console.log("→ JS-blocked SSR data-theme check (fail-closed)…")
  const ssrPage = await context.newPage()
  let abortedAppEntries = 0
  await ssrPage.route("**/src/app.ts", (r) => {
    abortedAppEntries++
    return r.abort()
  })
  // The project's Vite config emits a non-hashed `assets/app.js`
  // (see base.html's `{% static 'assets/app.js' %}` reference); intercept
  // the literal name. The hashed pattern is kept as forward-compat in
  // case Vite output is ever switched to hashed filenames — both
  // patterns count toward `abortedAppEntries`, and the startup assertion
  // below catches the case where neither matches (e.g. the entry name
  // moves out of `assets/`).
  await ssrPage.route("**/static/assets/app.js", (r) => {
    abortedAppEntries++
    return r.abort()
  })
  await ssrPage.route("**/static/assets/app-*.js", (r) => {
    abortedAppEntries++
    return r.abort()
  })
  await ssrPage.goto(`${BASE}/settings/`, { waitUntil: "domcontentloaded" })
  if (abortedAppEntries === 0) {
    throw new Error(
      "JS-blocked FOUC test wired wrong: no app-entry request was intercepted. " +
        "Did the bundle path change? Check Vite manifest output and update the route globs.",
    )
  }
  const ssrTheme = await ssrPage.getAttribute("html", "data-theme")
  if (ssrTheme !== "strategic") {
    throw new Error(
      `SSR data-theme=${JSON.stringify(ssrTheme)} (JS blocked), want 'strategic'. ` +
        "If you see 'classic' here, base.html's template_data wiring is missing.",
    )
  }

  console.log("\n✅ theme-switch-persistence: all 7 steps passed.")
} catch (err) {
  exitCode = 1
  console.error(`\n❌ ${err.message}`)
} finally {
  await browser.close()
  // Postflight (courtesy): reset preference back to classic so manual
  // testers start fresh after the script runs.
  try {
    shellExec(`
from templates_mgr.models import UserPreferences
from django.contrib.auth.models import User
u = User.objects.get(username='${USERNAME}')
UserPreferences.objects.filter(user=u).update(theme='classic')
print('postflight: theme reset to classic')
`)
  } catch (_) {
    // Non-fatal — the test result is already determined.
  }
  process.exit(exitCode)
}
