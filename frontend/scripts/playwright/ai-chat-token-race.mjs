// Feature 0007 — Test 12 of docs/features/0007_MANUAL_TEST.md:
// "Token-race: stale day-A response cannot leak into day-B thread".
//
// 💸 NO LLM CALL — both /chat/ requests are stubbed via page.route()
// with controlled delays so the race ordering is deterministic.
//
// Scenario:
//   1. Seed empty draft schedules on day A + day B.
//   2. page.route() differentiates by date:
//        - day-A /chat/ → delay 8s → synthetic 200 with block at 10:00
//        - day-B /chat/ → delay 2s → synthetic 200 with block at 11:00
//      This guarantees A always resolves AFTER B.
//   3. Submit prompt on day A → assert user bubble + spinner.
//   4. BEFORE A resolves, click next-day arrow → on day B assert
//      thread is empty and no spinner (clearThread on setActiveDate
//      bumped the token).
//   5. Submit different prompt on day B → assert user bubble +
//      spinner.
//   6. Wait ~2.5s for B to resolve → assert 2 bubbles (B's user +
//      B's assistant), no spinner, textarea enabled.
//   7. Wait the remaining ~6s for A's late response to arrive →
//      assert STILL 2 bubbles (no A leakage), no spinner.
//
// The invariant: `useChat.ts` `latestRequestId` advanced twice between
// A's start and A's resolve (once on clearThread, once on B's submit),
// so A's resolver finds `myId !== latestRequestId` and drops its writes.
//
// Run from frontend/:
//   node scripts/playwright/ai-chat-token-race.mjs
//
// Pre-reqs: Django :8006, Vite :5173, playwright user.
// LLM_API_KEY not required — chat calls are stubbed.
// ⚠️  LOCAL DEVELOPMENT ONLY. Seeds truncate target schedules' blocks.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const DAY_A = "2026-09-29"
const DAY_B = "2026-09-30"
const DAY_A_PARTS = [2026, 9, 29]
const DAY_B_PARTS = [2026, 9, 30]

const DELAY_A_MS = 8000
const DELAY_B_MS = 2000

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Seeding empty draft schedules on both days…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
for d in (datetime.date(${DAY_A_PARTS.join(', ')}), datetime.date(${DAY_B_PARTS.join(', ')})):
    s, _ = Schedule.objects.update_or_create(user=u, date=d, defaults={'status': 'draft'})
    TimeBlock.objects.filter(schedule=s).delete()
print('seeded both dates')
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

const responsesSeen = []
page.on("response", (resp) => {
  const m = resp.url().match(/\/api\/ai\/schedules\/([^/]+)\/chat\/$/)
  if (m) {
    responsesSeen.push({ date: m[1], status: resp.status(), at: Date.now() })
  }
})

// Stub both /chat/ endpoints with date-specific delays.
await page.route(/\/api\/ai\/schedules\/[^/]+\/chat\/$/, async (route) => {
  const m = route.request().url().match(/\/api\/ai\/schedules\/([^/]+)\/chat\/$/)
  const date = m?.[1]
  const isDayA = date === DAY_A
  const delay = isDayA ? DELAY_A_MS : DELAY_B_MS
  const block = isDayA
    ? { id: 7777, title: "day-A focus block", start_time: "10:00", end_time: "10:30", category: "other", is_completed: false, sort_order: 0 }
    : { id: 8888, title: "day-B coffee break", start_time: "11:00", end_time: "11:15", category: "personal", is_completed: false, sort_order: 0 }
  await new Promise((r) => setTimeout(r, delay))
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      blocks: [block],
      explanation: `stub for ${date}`,
      ask: null,
      applied: true,
    }),
  })
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

  console.log(`→ Opening /schedule/${DAY_A}/…`)
  await page.goto(`${BASE}/schedule/${DAY_A}/`, { waitUntil: "networkidle" })

  const inputEl = page.locator('[data-testid="chat-input"]')
  const thread = page.locator('[data-testid="chat-thread"]')
  const spinner = page.locator(".spinner")
  const nextDayBtn = page.locator(".right-controls button.nav-btn")

  // ─── Phase 1: submit on day A (8s delay) ────────────────────────────
  console.log("→ Phase 1: submit on day A…")
  const tA = Date.now()
  await inputEl.fill("add a 30-minute focus block at 10:00")
  await inputEl.press("Enter")
  await page.waitForTimeout(400)

  const bubblesA = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesA !== 1) {
    fail(`phase 1: expected 1 bubble (user-A) after submit, got ${bubblesA}`)
  }
  if (!(await spinner.isVisible())) {
    fail("phase 1: spinner not visible while day-A request in flight")
  }

  // ─── Phase 2: navigate to day B BEFORE A resolves ───────────────────
  console.log("→ Phase 2: navigate to day B before A resolves…")
  await nextDayBtn.click()
  // Wait for URL to flip.
  await page.waitForURL(new RegExp(`/schedule/${DAY_B}/`), { timeout: 5000 })
  await page.waitForTimeout(400)

  const bubblesAfterNav = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesAfterNav !== 0) {
    fail(`phase 2: expected 0 bubbles on day B after nav, got ${bubblesAfterNav}`)
  }
  if (await spinner.isVisible()) {
    fail("phase 2: spinner still visible after nav (clearThread did not reset isProcessing)")
  }
  if (await inputEl.isDisabled()) {
    fail("phase 2: textarea still disabled after nav")
  }

  // ─── Phase 3: submit different prompt on day B ──────────────────────
  console.log("→ Phase 3: submit on day B (2s delay)…")
  const tB = Date.now()
  await inputEl.fill("add a coffee break at 11:00")
  await inputEl.press("Enter")
  await page.waitForTimeout(400)

  const bubblesB1 = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesB1 !== 1) {
    fail(`phase 3: expected 1 bubble (user-B) after submit, got ${bubblesB1}`)
  }
  if (!(await spinner.isVisible())) {
    fail("phase 3: spinner not visible while day-B request in flight")
  }

  // ─── Phase 4: wait for B to resolve ─────────────────────────────────
  console.log("→ Phase 4: waiting for B to resolve…")
  // B started at tB, delay is 2000ms — wait 2.5s for safety.
  await page.waitForTimeout(DELAY_B_MS + 600)

  const bubblesPostB = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesPostB !== 2) {
    fail(`phase 4: expected 2 bubbles (user-B + assistant-B) after B resolves, got ${bubblesPostB}`)
  }
  if (await spinner.isVisible()) {
    fail("phase 4: spinner still visible after B resolves")
  }
  if (await inputEl.isDisabled()) {
    fail("phase 4: textarea still disabled after B resolves")
  }
  // Verify B's assistant bubble has the right content.
  const assistantText = (await thread.locator(".bubble").nth(1).textContent()) || ""
  if (!assistantText.includes(DAY_B)) {
    fail(`phase 4: assistant bubble text expected to reference ${DAY_B}, got "${assistantText.slice(0, 80)}"`)
  }

  // ─── Phase 5: wait for A's late response and assert no leakage ──────
  console.log("→ Phase 5: waiting for late day-A response to be dropped…")
  // A started at tA; need to wait until tA + DELAY_A_MS has elapsed.
  const elapsed = Date.now() - tA
  const remaining = Math.max(0, DELAY_A_MS - elapsed) + 1500
  await page.waitForTimeout(remaining)

  const dayAResponseSeen = responsesSeen.find((r) => r.date === DAY_A)
  if (!dayAResponseSeen) {
    fail("phase 5: day-A response never arrived — test cannot verify the race")
  }

  const bubblesPostA = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesPostA !== 2) {
    fail(`phase 5: expected 2 bubbles after A's late resolve (no leakage), got ${bubblesPostA}`)
  }
  // None of the bubbles should mention day A.
  const allBubbleTexts = await thread.locator(".bubble").allTextContents()
  if (allBubbleTexts.some((t) => t.includes(DAY_A))) {
    fail(`phase 5: a bubble references day A — leakage detected: ${JSON.stringify(allBubbleTexts)}`)
  }
  if (await spinner.isVisible()) {
    fail("phase 5: spinner reappeared after A's late resolve (stale resolver bug)")
  }

  console.log("\n=== Captured /chat/ responses ===")
  for (const r of responsesSeen) {
    console.log(`  date=${r.date} status=${r.status} at=${r.at}`)
  }
  console.log("\n=== Final thread ===")
  for (const t of allBubbleTexts) {
    console.log(`  bubble: ${t.slice(0, 100)}`)
  }

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — Test 12: stale day-A resolution did not leak into day-B thread")
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
