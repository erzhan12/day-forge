// Feature 0020 — Todoist connect + schedule panel smoke test.
//
// Verifies:
//   (a) Settings shows the Todoist section and connect form when disconnected.
//   (b) With TODOIST_API_TOKEN set: connect via Settings, panel appears on
//       Schedule, tasks load (or empty-state copy) without provider error.
//   (c) Disconnect restores hidden panel on Schedule.
//
// Run from frontend/:
//   TODOIST_API_TOKEN=<personal-token> node scripts/playwright/todoist-integration.mjs
//
// Headed (visible browser):
//   PLAYWRIGHT_HEADED=1 node scripts/playwright/todoist-integration.mjs
//
// Pre-reqs: Django :8006, Vite :5173, playwright user,
//           TODOIST_ENCRYPTION_KEY in backend .env (loaded by Django).
// ⚠️  LOCAL DEVELOPMENT ONLY. Preflight disconnects the playwright user's
// Todoist account so each run starts clean.

import { chromium } from "@playwright/test"
import {
  BASE,
  PANEL_TIMEOUT_MS,
  USERNAME,
  WAIT_FOR_THREAD_SETTLE_MS,
  failFast,
  login,
  preflight,
  seed,
} from "./test-utils.mjs"
const API_TOKEN = process.env.TODOIST_API_TOKEN?.trim() || ""

await preflight()
const fail = failFast

console.log("→ Preflight: disconnect playwright user's Todoist account…")
try {
  seed("seed_todoist", {
    SEED_MODE: "reset-strict",
    SEED_USERNAME: USERNAME,
  })
} catch (err) {
  console.error("\n❌ Preflight failed (is Django running? migrations applied?).")
  console.error(err.message)
  process.exit(2)
}

if (!API_TOKEN) {
  console.error(
    "\n❌ TODOIST_API_TOKEN is required for this script.",
  )
  console.error(
    "   Set your Todoist personal API token (Settings → Integrations → Developer).",
  )
  console.error(
    "   Example: TODOIST_API_TOKEN=... node scripts/playwright/todoist-integration.mjs",
  )
  process.exit(2)
}

const today = new Date().toISOString().slice(0, 10)
const headed = process.env.PLAYWRIGHT_HEADED === "1"
if (headed) {
  console.log("→ Headed mode: browser window will stay open until the script finishes.")
}

const browser = await chromium.launch({
  headless: !headed,
  slowMo: headed ? 300 : 0,
})
let exitCode = 0
try {
  const page = await browser.newPage()

  console.log("→ Logging in…")
  await login(page, { waitForUsername: true })

  console.log("→ Schedule: panel hidden when disconnected…")
  await page.goto(`${BASE}/schedule/${today}/`, { waitUntil: "networkidle" })
  if (await page.locator(".todoist-tasks").count()) {
    fail("Todoist panel visible before connect")
  }

  console.log("→ Settings: connect Todoist…")
  await page.goto(`${BASE}/settings/`, { waitUntil: "networkidle" })
  await page.waitForSelector('text=Todoist')
  const tokenInput = page.locator('section:has(h2:text("Todoist")) input[type="password"]')
  await tokenInput.fill(API_TOKEN)
  await Promise.all([
    page.waitForSelector('text=Connected to Todoist'),
    page.click('section:has(h2:text("Todoist")) button:has-text("Connect")'),
  ])

  console.log(`→ Schedule: panel visible after connect (${today})…`)
  await page.goto(`${BASE}/schedule/${today}/`, { waitUntil: "networkidle" })
  const panel = page.locator('[aria-label="Todoist tasks"]')
  await panel.waitFor({ state: "visible", timeout: PANEL_TIMEOUT_MS })

  const errorBanner = page.locator(".todoist-error")
  if (await errorBanner.count()) {
    const msg = await errorBanner.innerText()
    fail(`Todoist panel shows error after connect: ${msg}`)
  }

  const loading = page.locator(".todoist-loading")
  if (await loading.count()) {
    await loading.waitFor({ state: "hidden", timeout: PANEL_TIMEOUT_MS })
  }

  const taskCount = await page.locator('[data-testid="todoist-task"]').count()
  const emptyCopy = page.locator('text=No tasks scheduled for this day.')
  if (taskCount === 0 && (await emptyCopy.count()) === 0) {
    fail("Panel visible but neither tasks nor empty-state copy rendered")
  }
  console.log(`   tasks on panel: ${taskCount}`)

  console.log("→ Settings: disconnect…")
  await page.goto(`${BASE}/settings/`, { waitUntil: "networkidle" })
  await page.click('section:has(h2:text("Todoist")) button:has-text("Disconnect")')
  await page.waitForSelector('text=API token')

  console.log("→ Schedule: panel hidden after disconnect…")
  await page.goto(`${BASE}/schedule/${today}/`, { waitUntil: "networkidle" })
  await page.waitForTimeout(WAIT_FOR_THREAD_SETTLE_MS)
  if (await page.locator(".todoist-tasks").count()) {
    fail("Todoist panel still visible after disconnect")
  }

  console.log("\n✅ Todoist integration smoke passed.")
} catch (err) {
  console.error("\n❌ Todoist integration smoke failed.")
  console.error(err.message)
  exitCode = 1
} finally {
  await browser.close()
}

process.exit(exitCode)
