// Feature 0007 — Test 6 of docs/features/0007_MANUAL_TEST.md:
// "Privacy hint always visible".
//
// 💸 NO LLM CALL — the script intercepts /chat/ via page.route() and
// returns a synthetic 200 envelope. Test 6 is about UI invariants
// (presence + styling of the hint across state transitions), not model
// behaviour, so we don't need to spend a real call on it.
//
// Scenario:
//   1. Seed an empty draft schedule.
//   2. State A — fresh schedule, no prior thread:
//        - chat-privacy-hint visible
//        - chat-thread NOT rendered (no bubbles yet)
//   3. State B — after one synthetic-200 turn:
//        - hint still visible
//        - thread rendered with ≥2 bubbles below the hint
//        - hint sits ABOVE the thread in document order
//   4. State C — click clear:
//        - bubbles gone (chat-thread unmounted)
//        - hint still visible
//   5. State D — full page reload:
//        - hint visible immediately, before any input
//   6. Style check: 11px italic, centred, color #6b7280
//      (rgb(107, 114, 128)). The "one line" sub-bullet is left for the
//      manual eye — DPI/accessibility magnification can break it on
//      individual machines and the test plan acknowledges that.
//
// Run from frontend/:
//   node scripts/playwright/ai-chat-privacy-hint-always-on.mjs
//
// Pre-reqs: Django :8006, Vite :5173, playwright user.
// LLM_API_KEY is NOT required because the chat call is stubbed.
// ⚠️  LOCAL DEVELOPMENT ONLY. The seed step truncates the target
// schedule's blocks.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const SCHEDULE_DATE = "2026-09-27"
const SCHEDULE_DATE_PARTS = [2026, 9, 27]

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

// Stub /chat/ with a successful envelope. The exact block content is
// irrelevant for Test 6 — we only need the response to be 200 + valid
// JSON so `useChat` appends the assistant bubble and the thread renders.
await page.route(/\/api\/ai\/schedules\/[^/]+\/chat\/$/, async (route) => {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      blocks: [
        {
          id: 9999,
          title: "stub block",
          start_time: "10:00",
          end_time: "10:30",
          category: "other",
          is_completed: false,
          sort_order: 0,
        },
      ],
      explanation: "stub assistant reply for test 6",
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

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, { waitUntil: "networkidle" })

  const privacyHint = page.locator('[data-testid="chat-privacy-hint"]')
  const thread = page.locator('[data-testid="chat-thread"]')
  const inputEl = page.locator('[data-testid="chat-input"]')
  const clearBtn = page.locator('[data-testid="chat-clear"]')

  // ─── State A: fresh schedule, no thread ─────────────────────────────
  console.log("→ State A: fresh schedule…")
  if (!(await privacyHint.isVisible())) {
    fail("State A: privacy hint not visible on fresh schedule (iter-5 always-on regression)")
  }
  const hintText = (await privacyHint.textContent()) || ""
  if (!hintText.includes("Full chat history is re-sent to the AI provider")) {
    fail(`State A: privacy hint text unexpected: ${hintText.slice(0, 80)}`)
  }
  if ((await thread.count()) > 0) {
    fail("State A: chat-thread rendered before any turn (should be hidden until visibleMessages > 0)")
  }

  // ─── Style check ───────────────────────────────────────────────────
  console.log("→ Style check: 11px italic centred #6b7280…")
  const styles = await privacyHint.evaluate((el) => {
    const s = getComputedStyle(el)
    return {
      fontSize: s.fontSize,
      fontStyle: s.fontStyle,
      color: s.color,
      textAlign: s.textAlign,
    }
  })
  if (styles.fontSize !== "11px") {
    fail(`style: font-size expected 11px, got ${styles.fontSize}`)
  }
  if (styles.fontStyle !== "italic") {
    fail(`style: font-style expected italic, got ${styles.fontStyle}`)
  }
  if (styles.color !== "rgb(107, 114, 128)") {
    fail(`style: color expected rgb(107, 114, 128) [#6b7280], got ${styles.color}`)
  }
  if (styles.textAlign !== "center") {
    fail(`style: text-align expected center, got ${styles.textAlign}`)
  }

  // ─── State B: after a stubbed-200 turn ──────────────────────────────
  console.log("→ State B: after one stubbed-200 turn…")
  await inputEl.fill("test 6 — stubbed turn")
  await Promise.all([
    page.waitForResponse(
      (resp) => /\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(resp.url()),
      { timeout: 10_000 },
    ),
    inputEl.press("Enter"),
  ])
  await page.waitForTimeout(500)

  if (!(await privacyHint.isVisible())) {
    fail("State B: privacy hint disappeared after sending a turn")
  }
  await thread.waitFor({ timeout: 4000 }).catch(() => {})
  const bubblesB = await thread.locator(".bubble").count().catch(() => 0)
  if (bubblesB < 2) {
    fail(`State B: expected ≥2 bubbles after turn, got ${bubblesB}`)
  }

  // Document-order check: hint must precede the thread.
  const order = await page.evaluate(() => {
    const hint = document.querySelector('[data-testid="chat-privacy-hint"]')
    const thr = document.querySelector('[data-testid="chat-thread"]')
    if (!hint || !thr) return "missing-element"
    const cmp = hint.compareDocumentPosition(thr)
    // DOCUMENT_POSITION_FOLLOWING = 4
    return cmp & 4 ? "hint-before-thread" : "thread-before-hint"
  })
  if (order !== "hint-before-thread") {
    fail(`State B: expected hint to precede thread in DOM order, got ${order}`)
  }

  // ─── State C: click clear ───────────────────────────────────────────
  console.log("→ State C: click clear…")
  await clearBtn.click()
  await page.waitForTimeout(200)
  if (!(await privacyHint.isVisible())) {
    fail("State C: privacy hint disappeared after clear")
  }
  if ((await thread.count()) > 0) {
    fail("State C: chat-thread still rendered after clear")
  }

  // ─── State D: full page reload ──────────────────────────────────────
  console.log("→ State D: full page reload…")
  await page.reload({ waitUntil: "networkidle" })
  if (!(await privacyHint.isVisible())) {
    fail("State D: privacy hint not visible immediately after reload")
  }
  if ((await thread.count()) > 0) {
    fail("State D: chat-thread rendered immediately after reload (no per-tab persistence expected)")
  }

  // ─── Verdict ────────────────────────────────────────────────────────
  console.log("\n=== Computed styles on privacy hint ===")
  console.log(`  font-size: ${styles.fontSize}`)
  console.log(`  font-style: ${styles.fontStyle}`)
  console.log(`  color: ${styles.color}`)
  console.log(`  text-align: ${styles.textAlign}`)

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — Test 6: privacy hint is always visible across A/B/C/D and styled correctly")
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
