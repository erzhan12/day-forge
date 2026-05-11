// Feature 0007 — Test 4 of docs/features/0007_MANUAL_TEST.md:
// "Clear-thread is a logical cancel (in-flight + state reset)".
//
// 💸 COST WARNING — UP TO TWO real LLM calls per run (success + error
// path). The error path uses page.route() to fulfill the second request
// locally with a synthetic 500, so only the first turn actually hits
// the provider.
//
// Scenario (success path):
//   1. Seed an empty draft schedule.
//   2. page.route() the /chat/ endpoint to delay the response by ~6s
//      (simulates the manual-test "Slow 3G" instruction without needing
//      DevTools throttle).
//   3. Type a prompt, press Enter. Spinner appears, user bubble is
//      visible immediately.
//   4. While the request is still in flight, click [data-testid="chat-clear"].
//      This is the regression target for the iter-fix that decoupled
//      the clear button's `disabled` state from `isProcessing`. Before
//      the fix the button was greyed out exactly while the user needed
//      it most.
//   5. Immediately assert:
//        - thread bubbles count == 0
//        - textarea is enabled (NOT disabled)
//        - privacy hint still visible
//   6. Wait for the late /chat/ response to actually land.
//   7. Assert nothing new appears:
//        - thread bubbles count is still 0 (no synthetic late bubble)
//        - no .error-row (lastError not set)
//
// Error-path repeat:
//   8. page.route() to delay AND fulfill the response with HTTP 500.
//   9. Send another prompt, click clear mid-flight.
//   10. Assert: still 0 bubbles, no .error-row after the synthetic 500
//       arrives — the cancelled-thread guard must apply to errors too.
//
// Run from frontend/:
//   node scripts/playwright/ai-chat-clear-cancels-inflight.mjs
//
// Pre-reqs: Django :8006, Vite :5173, playwright user, LLM_API_KEY set.
// ⚠️  LOCAL DEVELOPMENT ONLY. The seed step truncates the target
// schedule's blocks.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// Distinct date so concurrent runs don't stomp other scripts' seeds.
const SCHEDULE_DATE = "2026-09-26"
const SCHEDULE_DATE_PARTS = [2026, 9, 26]
const DELAY_MS = 6000

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Seeding empty draft schedule…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
s, _ = Schedule.objects.update_or_create(
    user=u, date=datetime.date(${SCHEDULE_DATE_PARTS.join(', ')}), defaults={'status': 'draft'}
)
TimeBlock.objects.filter(schedule=s).delete()
print('seeded empty schedule', s.id)
"`,
    { stdio: "inherit", cwd: REPO_ROOT },
  )
} catch (err) {
  console.error("\n❌ Seed failed.")
  console.error(err.message)
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } })
const page = await context.newPage()

const failures = []
const fail = (msg) => failures.push(msg)

// State for route handlers — flipped between phases.
let routeMode = "delay-passthrough" // or "delay-fulfill-500" or "off"

await page.route(
  /\/api\/ai\/schedules\/[^/]+\/chat\/$/,
  async (route) => {
    if (routeMode === "off") {
      return route.continue()
    }
    await new Promise((r) => setTimeout(r, DELAY_MS))
    if (routeMode === "delay-fulfill-500") {
      return route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ errors: { detail: "synthetic 500 for test 4" } }),
      })
    }
    return route.continue()
  },
)

const responsesSeen = []
page.on("response", (resp) => {
  if (/\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(resp.url())) {
    responsesSeen.push({ status: resp.status(), at: Date.now() })
  }
})

try {
  console.log("→ Logging in…")
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, { waitUntil: "networkidle" })

  const inputEl = page.locator('[data-testid="chat-input"]')
  const clearBtn = page.locator('[data-testid="chat-clear"]')
  const thread = page.locator('[data-testid="chat-thread"]')
  const privacyHint = page.locator('[data-testid="chat-privacy-hint"]')
  const errorRow = page.locator(".error-row")

  // ───────────────── PHASE 1: success-path delay → cancel ─────────────────
  console.log("→ Phase 1: in-flight cancel against a delayed 200…")
  routeMode = "delay-passthrough"
  await inputEl.fill("add gym at 18:00 for an hour")
  // Don't await the response — the route delays it 6s.
  await inputEl.press("Enter")

  // Wait briefly for the user bubble + spinner to appear.
  await page.waitForTimeout(600)

  // Clear button must be visible AND not disabled. This is the
  // regression target — pre-fix it was greyed out by `inputDisabled`.
  if (!(await clearBtn.isVisible())) {
    fail("phase 1: clear button not visible while request in flight")
  }
  const clearDisabledMid = await clearBtn.isDisabled()
  if (clearDisabledMid) {
    fail("phase 1: clear button is DISABLED while request in flight (regression — should be clickable)")
  }

  // Click clear while the response is still in flight.
  await clearBtn.click()

  // Immediate assertions.
  const bubblesAfterClearP1 = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesAfterClearP1 !== 0) {
    fail(`phase 1: expected 0 bubbles immediately after clear, got ${bubblesAfterClearP1}`)
  }
  if (await inputEl.isDisabled()) {
    fail("phase 1: textarea still disabled after clear (token bump didn't reset isProcessing)")
  }
  if (!(await privacyHint.isVisible())) {
    fail("phase 1: privacy hint vanished after clear (should always be visible)")
  }

  // Now wait for the late response to actually arrive and be dropped.
  console.log("  …waiting for the delayed response to land and be dropped…")
  const beforeWaitCount = responsesSeen.length
  await page.waitForFunction(
    (n) => window.performance.getEntriesByType("resource").filter((e) => /\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(e.name)).length > n,
    beforeWaitCount,
    { timeout: 15_000 },
  ).catch(() => {})
  // Give Vue a moment to (NOT) react.
  await page.waitForTimeout(800)

  const bubblesPostResponseP1 = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesPostResponseP1 !== 0) {
    fail(`phase 1: expected 0 bubbles after late response, got ${bubblesPostResponseP1} (stale token check failed)`)
  }
  if ((await errorRow.count()) > 0) {
    fail("phase 1: .error-row appeared after late response was dropped")
  }

  // ───────────────── PHASE 2: error-path delay → cancel ─────────────────
  console.log("→ Phase 2: in-flight cancel against a delayed 500…")
  routeMode = "delay-fulfill-500"
  await inputEl.fill("add a coffee at 09:00")
  await inputEl.press("Enter")
  await page.waitForTimeout(600)

  if (await clearBtn.isDisabled()) {
    fail("phase 2: clear button disabled while error-path request in flight")
  }
  await clearBtn.click()

  const bubblesAfterClearP2 = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesAfterClearP2 !== 0) {
    fail(`phase 2: expected 0 bubbles immediately after clear, got ${bubblesAfterClearP2}`)
  }
  if (await inputEl.isDisabled()) {
    fail("phase 2: textarea still disabled after clear")
  }

  console.log("  …waiting for the delayed 500 to land and be dropped…")
  await page.waitForTimeout(DELAY_MS + 1500)

  const bubblesPostResponseP2 = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesPostResponseP2 !== 0) {
    fail(`phase 2: expected 0 bubbles after late 500, got ${bubblesPostResponseP2}`)
  }
  if ((await errorRow.count()) > 0) {
    fail("phase 2: .error-row appeared after late 500 was dropped (stale-error guard failed)")
  }

  // ───────────────── Diagnostics ─────────────────
  console.log("\n=== Captured chat responses ===")
  for (const r of responsesSeen) {
    console.log(`  status=${r.status} t=${r.at}`)
  }

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — Test 4: clear is a logical cancel for both 200 and 500 in-flight responses")
    process.exitCode = 0
  } else {
    console.log("❌ FAIL —")
    for (const r of failures) console.log(`    • ${r}`)
    process.exitCode = 1
  }
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
