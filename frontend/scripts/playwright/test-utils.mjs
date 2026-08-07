import { execSync } from "node:child_process"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

export const BASE = "http://localhost:5173"
export const USERNAME = "playwright"
export const PASSWORD = "playwright-pw-do-not-use-in-prod"
// Anchor on this file's location (frontend/scripts/playwright/test-utils.mjs)
// so REPO_ROOT is correct no matter the cwd a script is invoked from.
export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..")

export const WAIT_FOR_UI_TICK_MS = 200
export const WAIT_FOR_SHORT_SETTLE_MS = 300
export const WAIT_FOR_INERTIA_SETTLE_MS = 400
export const WAIT_FOR_THREAD_SETTLE_MS = 500
export const WAIT_FOR_INFLIGHT_RENDER_MS = 600
export const WAIT_FOR_LATE_RESPONSE_SETTLE_MS = 800
export const WAIT_FOR_DRAFT_OVERLAY_MS = 1200
export const WAIT_FOR_PATCH_MS = 1500
export const WAIT_FOR_AUTO_DRAFT_MS = 2000
export const RESPONSE_TIMEOUT_MS = 25_000
export const DRAFT_RESPONSE_TIMEOUT_MS = 60_000
export const CAPTURE_RESPONSE_TIMEOUT_MS = 120_000
export const ELEMENT_TIMEOUT_MS = 5_000
export const PANEL_TIMEOUT_MS = 15_000
export const UI_RESPONSE_TIMEOUT_MS = 10_000
export const CHAT_INPUT_TIMEOUT_MS = 3_000
export const CHAT_THREAD_TIMEOUT_MS = 4_000
export const INPUT_TIMEOUT_MS = 2_000
export const ANALYTICS_BUTTON_TIMEOUT_MS = 8_000

export const CLEANUP_ENABLED = process.argv.includes("--cleanup")

export function makeFailAggregator() {
  const failures = []
  return {
    failures,
    fail(message) {
      failures.push(message)
    },
  }
}

export function failFast(message) {
  throw new Error(message)
}

export async function login(page, options = {}) {
  const {
    usernameSelector = "#username",
    passwordSelector = "#password",
    waitUntil = "networkidle",
    waitForUsername = false,
  } = options
  const gotoOptions = waitUntil ? { waitUntil } : undefined
  await page.goto(`${BASE}/accounts/login/`, gotoOptions)
  if (waitForUsername) await page.waitForSelector(usernameSelector)
  await page.fill(usernameSelector, USERNAME)
  await page.fill(passwordSelector, PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])
}

export async function preflight() {
  try {
    const response = await fetch(`${BASE}/accounts/login/`, { method: "GET" })
    if (response.status < 200 || response.status >= 400) {
      throw new Error(`HTTP ${response.status}`)
    }
  } catch (error) {
    console.error("\n❌ Day Forge dev stack is not reachable.")
    console.error("   Start Django with `make run` and Vite with `make frontend-dev`.")
    console.error(`   ${error.message}`)
    process.exit(2)
  }
}

export function preflightUser() {
  try {
    const output = seed(
      "seed_schedule",
      { SEED_MODE: "user_exists", SEED_USERNAME: USERNAME },
      { encoding: "utf8" },
    )
    if (!output.includes("EXISTS True")) {
      console.error("\n❌ playwright user is missing. Run:")
      console.error("   uv run python backend/manage.py createsuperuser")
      console.error(`   (use username '${USERNAME}' / password '${PASSWORD}')`)
      process.exit(2)
    }
  } catch (error) {
    console.error("\n❌ Pre-flight shell failed:", error.message)
    process.exit(2)
  }
}

export async function postWithCsrf(page, url, body) {
  return page.evaluate(
    async ({ requestUrl, requestBody }) => {
      const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
      const csrf = match ? decodeURIComponent(match[1]) : ""
      if (!csrf) return { error: "no XSRF-TOKEN cookie present" }
      const response = await fetch(requestUrl, {
        method: "POST",
        credentials: "include",
        headers: {
          "content-type": "application/json",
          "x-xsrf-token": csrf,
        },
        body: JSON.stringify(requestBody),
      })
      return { status: response.status, body: await response.text() }
    },
    { requestUrl: url, requestBody: body },
  )
}

export function seed(scriptName, env = {}, options = {}) {
  if (!/^[a-z0-9_]+$/.test(scriptName)) {
    throw new Error(`Invalid seed script name: ${scriptName}`)
  }
  const command =
    `uv run python backend/manage.py shell -c ` +
    `"import runpy; runpy.run_path('backend/scripts/${scriptName}.py', run_name='__main__')"`
  const execOptions = {
    cwd: REPO_ROOT,
    env: { ...process.env, ...env },
    ...options,
  }
  if (!("encoding" in execOptions) && !("stdio" in execOptions)) {
    execOptions.stdio = "inherit"
  }
  return execSync(command, execOptions)
}

export function djangoToday() {
  const output = seed(
    "seed_schedule",
    { SEED_MODE: "localdate" },
    { encoding: "utf8" },
  )
  const match = output.match(/^\d{4}-\d{2}-\d{2}$/m)
  if (!match) throw new Error(`could not parse Django date from:\n${output}`)
  return match[0]
}

export function cleanupSchedules(dates, username = USERNAME) {
  if (!CLEANUP_ENABLED || dates.length === 0) return
  seed("seed_cleanup", {
    SEED_USERNAME: username,
    SEED_DATES_JSON: JSON.stringify(dates),
  })
}
