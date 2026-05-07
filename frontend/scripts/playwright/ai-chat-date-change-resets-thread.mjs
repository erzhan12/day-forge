// Feature 0007: chat thread is auto-reset when the user navigates to a
// different schedule date (DateNavigator). Without this, a follow-up
// like "ага, добавь его" authored against day A could mutate day B.
//
// 💸 COST WARNING — UP TO TWO real LLM calls (one per chat submit
// before/after navigation). The script's value is end-to-end: it
// verifies that `useChat.setActiveDate` is wired into the Schedule.vue
// `watch(props.date)` watcher AND that the request body for the second
// turn does NOT include the day-A transcript.
//
// Scenario:
//   1. Seed empty draft schedules on two adjacent far-future dates.
//   2. Open day A, send turn 1, capture the chat request — must
//      contain exactly one user message.
//   3. Navigate to day B via DateNavigator (next-day arrow).
//   4. Send turn 2, capture the chat request — must contain exactly
//      one user message (NOT the day-A history) and the URL must
//      target day B.
//   5. Assert the chat thread above the textarea is fresh (only the
//      day-B user bubble plus its assistant reply).
//
// Run from frontend/:
//   node scripts/playwright/ai-chat-date-change-resets-thread.mjs
//
// Pre-reqs: Django :8006, Vite :5173, `playwright` user, LLM_API_KEY set.
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// Two adjacent far-future dates. Day A → day B by clicking the
// DateNavigator's "next" arrow exactly once.
const DAY_A = "2026-09-22"
const DAY_B = "2026-09-23"

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Seeding empty draft schedules on both dates…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
for d in [datetime.date(2026, 9, 22), datetime.date(2026, 9, 23)]:
    s, _ = Schedule.objects.update_or_create(
        user=u, date=d, defaults={'status': 'draft'}
    )
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
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
})
const page = await context.newPage()

const chatCalls = []
page.on("response", async (resp) => {
  const url = resp.url()
  if (/\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(url)) {
    let bodyText = ""
    try {
      bodyText = await resp.text()
    } catch {
      bodyText = "(could not read body)"
    }
    let requestBody = ""
    try {
      requestBody = resp.request().postData() || ""
    } catch {
      requestBody = "(could not read request body)"
    }
    chatCalls.push({
      url,
      status: resp.status(),
      requestBody,
      responseBody: bodyText,
    })
  }
})

async function submitChatTurn(text) {
  const ta = page.locator('[data-testid="chat-input"]')
  await ta.waitFor({ timeout: 3000 })
  await ta.fill(text)
  await Promise.all([
    page.waitForResponse(
      (resp) => /\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(resp.url()),
      { timeout: 25_000 },
    ),
    ta.press("Enter"),
  ])
  await page.waitForTimeout(500)
}

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

  // Install a window marker BEFORE we do anything chat-related. This
  // is the regression guard: if navigation triggers a hard document
  // reload (e.g. someone replaces the DateNavigator's `router.visit`
  // with a `<a href>` that breaks Inertia, or this script regresses
  // back to `page.goto`), the marker is wiped and `useChat`'s
  // module-level state resets even without the Schedule.vue watcher.
  // A passing test under hard-reload would prove nothing about the
  // watcher; the marker forces same-document navigation.
  await page.evaluate(() => {
    // eslint-disable-next-line no-undef
    window.__PLAYWRIGHT_NAV_MARKER__ = true
  })

  console.log("→ Turn 1 on day A…")
  await submitChatTurn("какой у меня план на день?")

  // Snapshot bubble count on day A so we can compare after navigation.
  const dayABubbles = await page.locator('[data-testid="chat-thread"] .bubble').count()
  console.log(`→ Day A thread bubble count after turn 1: ${dayABubbles}`)

  console.log(`→ Navigating to /schedule/${DAY_B}/ via DateNavigator next-day click…`)
  // Click the DateNavigator "next" button — it calls
  // ``router.visit(...)`` (Inertia same-component navigation), which
  // keeps the Schedule.vue component instance mounted and fires the
  // ``watch(() => props.date, setChatActiveDate)`` watcher. This is
  // the actual user path; ``page.goto`` would do a hard browser
  // reload that resets ``useChat`` module-level state regardless of
  // whether the watcher works, defeating the test.
  // Selector: the next-day arrow is the second `button.nav-btn` inside
  // `.right-controls` (the first DOM child there is a Settings <a>).
  await Promise.all([
    page.waitForURL(`**/schedule/${DAY_B}/`),
    page.locator(".right-controls button.nav-btn").click(),
  ])
  // Wait for Inertia to swap props + Vue to settle.
  await page.waitForTimeout(300)

  // Same-document guarantee: the marker we installed pre-navigation
  // must survive the navigation. If it's gone, the browser did a
  // full-page reload and the test would be vacuously passing.
  const markerSurvived = await page.evaluate(
    () =>
      // eslint-disable-next-line no-undef
      typeof window.__PLAYWRIGHT_NAV_MARKER__ !== "undefined",
  )
  console.log(`→ Same-document navigation: ${markerSurvived ? "yes" : "NO (hard reload!)"}`)

  // After navigation, the thread MUST be empty (the watcher in
  // Schedule.vue calls useChat().setActiveDate(d) which triggers
  // clearThread on a different date).
  const postNavBubbles = await page
    .locator('[data-testid="chat-thread"] .bubble')
    .count()
  console.log(`→ Day B thread bubble count immediately after navigation: ${postNavBubbles}`)

  console.log("→ Turn 2 on day B…")
  await submitChatTurn("привет, как дела?")

  console.log("\n=== Captured chat calls ===")
  for (const [i, call] of chatCalls.entries()) {
    console.log(`Turn ${i + 1}: ${call.url}`)
    console.log(`  status=${call.status}`)
    console.log(`  Request body: ${call.requestBody.slice(0, 300)}`)
  }

  console.log("\n=== Verdict ===")
  let pass = true
  const reasons = []

  if (chatCalls.length !== 2) {
    pass = false
    reasons.push(`expected 2 chat calls, got ${chatCalls.length}`)
  } else {
    const [t1, t2] = chatCalls
    if (!t1.url.includes(`/schedules/${DAY_A}/chat/`)) {
      pass = false
      reasons.push(`turn 1 URL did not target day A: ${t1.url}`)
    }
    if (!t2.url.includes(`/schedules/${DAY_B}/chat/`)) {
      pass = false
      reasons.push(`turn 2 URL did not target day B: ${t2.url}`)
    }

    // The headline assertion: turn 2's transcript MUST contain only
    // the latest user message (1 entry), NOT the day-A history. If
    // the watcher were missing, the thread would still hold day-A's
    // user + assistant bubbles and turn 2 would carry length 3.
    let t2Req
    try {
      t2Req = JSON.parse(t2.requestBody)
    } catch {
      pass = false
      reasons.push("turn 2 request body is not JSON")
    }
    if (t2Req) {
      if (!Array.isArray(t2Req.messages)) {
        pass = false
        reasons.push("turn 2 request.messages is not an array")
      } else if (t2Req.messages.length !== 1) {
        pass = false
        reasons.push(
          `turn 2 transcript leaked day-A history: messages.length=${t2Req.messages.length}, expected 1`,
        )
      } else if (t2Req.messages[0].role !== "user") {
        pass = false
        reasons.push(`turn 2 first message role is ${t2Req.messages[0].role}, expected user`)
      } else if (t2Req.messages[0].content !== "привет, как дела?") {
        pass = false
        reasons.push(
          `turn 2 first message content unexpected: ${JSON.stringify(t2Req.messages[0].content)}`,
        )
      }
    }
  }

  if (postNavBubbles !== 0) {
    pass = false
    reasons.push(
      `expected 0 bubbles immediately after navigating to day B, got ${postNavBubbles}`,
    )
  }

  if (!markerSurvived) {
    pass = false
    reasons.push(
      "navigation triggered a full document reload — test is vacuous, " +
        "Schedule.vue watcher coverage is not actually exercised",
    )
  }

  if (pass) {
    console.log("✅ PASS — date navigation resets the chat thread")
  } else {
    console.log("❌ FAIL —")
    for (const r of reasons) console.log(`    • ${r}`)
  }
  process.exitCode = pass ? 0 : 1
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
