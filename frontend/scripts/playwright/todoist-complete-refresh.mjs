// Feature 0021 — Todoist complete-task + live-refresh smoke test.
//
// Verifies end-to-end (real Todoist API):
//   (a) A task shows on the Schedule sidebar after connect.
//   (b) Clicking its complete checkbox fires POST /complete/ (200) and the
//       row disappears optimistically.
//   (c) Clicking the header Refresh button fires GET ...?refresh=1 and the
//       completed task does NOT reappear (server-side cache invalidation +
//       live re-fetch), with no error banner.
//
// SAFETY: this script does NOT touch your real tasks. It creates a single
// throwaway task ("[DayForge E2E] …") due today via the Todoist API and
// completes THAT one. Completing is irreversible in this feature (no
// un-complete) — but the only task completed is the throwaway one. The
// `finally` block closes the throwaway task via API if the UI step never
// ran (e.g. on early failure) so nothing is left dangling.
//
// Run from frontend/:
//   TODOIST_API_TOKEN=<token> node scripts/playwright/todoist-complete-refresh.mjs
//   PLAYWRIGHT_HEADED=1 ...   (visible browser)
//
// Pre-reqs: Django :8006, Vite :5173, Redis up, playwright user,
//           TODOIST_ENCRYPTION_KEY in .env (loaded by Django).
// ⚠️  LOCAL DEVELOPMENT ONLY. Preflight disconnects the playwright user's
// Todoist account so each run starts clean.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"
const API_TOKEN = process.env.TODOIST_API_TOKEN?.trim() || ""
const TODOIST_BASE_URL = (
  process.env.TODOIST_BASE_URL?.trim() || "https://api.todoist.com/api/v1"
).replace(/\/$/, "")
const REPO_ROOT = resolve(process.cwd(), "..")

// Browser-local "today" (matches the frontend `todayString()` so the
// schedule URL date and the task's due date line up regardless of UTC drift).
const now = new Date()
const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`
const TASK_TITLE = `[DayForge E2E] complete ${new Date().toISOString()}`

function fail(msg) {
  // Throw (not process.exit) so the `finally` cleanup always runs.
  throw new Error(msg)
}

function shellExec(script) {
  execSync(`uv run python backend/manage.py shell -c "${script}"`, {
    stdio: "inherit",
    cwd: REPO_ROOT,
  })
}

async function todoistApi(method, path, body) {
  const resp = await fetch(`${TODOIST_BASE_URL}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${API_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  return resp
}

if (!API_TOKEN) {
  console.error("\n❌ TODOIST_API_TOKEN is required for this script.")
  process.exit(2)
}

console.log("→ Preflight: ensure playwright user exists + disconnect Todoist…")
try {
  shellExec(`
from django.contrib.auth.models import User
from todoist_sync.models import TodoistAccount
u, created = User.objects.get_or_create(username='${USERNAME}')
if created:
    u.set_password('${PASSWORD}')
    u.save()
deleted, _ = TodoistAccount.objects.filter(user=u).delete()
print('user created:', created, '| deleted todoist accounts:', deleted)
`)
} catch (err) {
  console.error("\n❌ Preflight failed (is Django running? migrations applied?).")
  console.error(err.message)
  process.exit(2)
}

console.log("→ Creating throwaway task via Todoist API…")
let taskId = null
let taskCompleted = false
{
  const resp = await todoistApi("POST", "/tasks", {
    content: TASK_TITLE,
    due_date: today,
  })
  if (!resp.ok) {
    console.error(`\n❌ Could not create the test task (HTTP ${resp.status}).`)
    console.error(await resp.text())
    process.exit(2)
  }
  const task = await resp.json()
  taskId = task.id
  console.log(`   created task id=${taskId} due=${today}`)
}

const headed = process.env.PLAYWRIGHT_HEADED === "1"
const browser = await chromium.launch({
  headless: !headed,
  slowMo: headed ? 300 : 0,
})
let exitCode = 0
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })

  console.log("→ Logging in…")
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.waitForSelector("#username")
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])

  console.log("→ Settings: connect Todoist…")
  await page.goto(`${BASE}/settings/`, { waitUntil: "networkidle" })
  await page.waitForSelector("text=Todoist")
  const tokenInput = page.locator(
    'section:has(h2:text("Todoist")) input[type="password"]',
  )
  await tokenInput.fill(API_TOKEN)
  await Promise.all([
    page.waitForSelector("text=Connected to Todoist"),
    page.click('section:has(h2:text("Todoist")) button:has-text("Connect")'),
  ])

  console.log(`→ Schedule ${today}: wait for the panel…`)
  await page.goto(`${BASE}/schedule/${today}/`, { waitUntil: "networkidle" })
  const panel = page.locator('[aria-label="Todoist tasks"]')
  await panel.waitFor({ state: "visible", timeout: 15000 })

  // Ensure the sidebar is expanded (Refresh button + task list only render
  // when open). If collapsed, click the rail toggle to expand.
  let refreshBtn = page.locator('[data-testid="todoist-sidebar-refresh"]')
  if ((await refreshBtn.count()) === 0) {
    console.log("   sidebar collapsed → expanding…")
    await page.locator('[data-testid="todoist-sidebar-toggle"]').first().click()
    refreshBtn = page.locator('[data-testid="todoist-sidebar-refresh"]')
  }
  await refreshBtn.waitFor({ state: "visible", timeout: 10000 })

  const loading = page.locator(".todoist-loading")
  if (await loading.count()) {
    await loading.waitFor({ state: "hidden", timeout: 15000 })
  }
  if (await page.locator(".todoist-error").count()) {
    fail(`Panel shows an error after connect: ${await page.locator(".todoist-error").innerText()}`)
  }

  console.log("→ Waiting for the throwaway task row to appear…")
  const testRow = page.locator('[data-testid="todoist-task"]', {
    hasText: TASK_TITLE,
  })
  await testRow.waitFor({ state: "visible", timeout: 15000 })
  console.log("   row present ✔")

  console.log("→ Complete the task (checkbox → POST /complete/)…")
  const completeCheckbox = testRow.locator('[data-testid="todoist-complete"]')
  // Use click(), NOT check(): the @change handler optimistically removes the
  // row, so the checkbox is detached before Playwright could confirm
  // `checked === true` — check() would time out. A click still toggles +
  // fires `change`, which is all the handler needs.
  const [completeResp] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes("/complete/") && r.request().method() === "POST",
      { timeout: 15000 },
    ),
    completeCheckbox.click(),
  ])
  if (completeResp.status() !== 200) {
    fail(`POST /complete/ returned ${completeResp.status()} (expected 200)`)
  }
  taskCompleted = true
  console.log(`   complete POST → ${completeResp.status()} ✔`)

  console.log("→ Assert the row disappeared optimistically…")
  await page.waitForFunction(
    (title) =>
      ![...document.querySelectorAll('[data-testid="todoist-task"]')].some(
        (el) => el.textContent.includes(title),
      ),
    TASK_TITLE,
    { timeout: 10000 },
  )
  if (await page.locator(".todoist-error").count()) {
    fail(`Error banner shown after a successful complete: ${await page.locator(".todoist-error").innerText()}`)
  }
  console.log("   row gone, no error ✔")

  console.log("→ Refresh (button → GET ...?refresh=1)…")
  const [refreshResp] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes("/api/todoist/tasks/") &&
        r.url().includes("refresh=1"),
      { timeout: 15000 },
    ),
    refreshBtn.click(),
  ])
  if (!refreshResp.ok()) {
    fail(`Refresh GET returned ${refreshResp.status()} (expected 2xx)`)
  }
  console.log(`   refresh GET refresh=1 → ${refreshResp.status()} ✔`)

  // Give the silent refetch a moment to commit, then confirm the completed
  // task did NOT come back and no skeleton/error is stuck.
  await page.waitForTimeout(800)
  if (await page.locator(".todoist-error").count()) {
    fail(`Error after refresh: ${await page.locator(".todoist-error").innerText()}`)
  }
  const cameBack = await page
    .locator('[data-testid="todoist-task"]', { hasText: TASK_TITLE })
    .count()
  if (cameBack !== 0) {
    fail("Completed task reappeared after refresh (cache not invalidated / not closed)")
  }
  console.log("   completed task stays gone after refresh ✔")

  console.log("\n✅ Todoist complete + refresh smoke passed.")
} catch (err) {
  exitCode = 1
  console.error("\n❌ Todoist complete + refresh smoke failed.")
  console.error(err.message)
} finally {
  // Cleanup 1: if the UI never completed the throwaway task (early failure),
  // close it via API so nothing is left open in the account.
  if (taskId && !taskCompleted) {
    try {
      const r = await todoistApi("POST", `/tasks/${taskId}/close`)
      console.log(`→ Cleanup: closed throwaway task via API (HTTP ${r.status}).`)
    } catch {
      console.log("→ Cleanup: could not close throwaway task via API (ignore).")
    }
  }
  await browser.close()
  // Cleanup 2: disconnect the playwright user's Todoist account.
  try {
    shellExec(`
from django.contrib.auth.models import User
from todoist_sync.models import TodoistAccount
u = User.objects.get(username='${USERNAME}')
TodoistAccount.objects.filter(user=u).delete()
print('disconnected playwright todoist account')
`)
  } catch {
    /* best-effort */
  }
}

process.exit(exitCode)
