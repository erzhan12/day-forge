// Feature 0007 — Test 1 of docs/features/0007_MANUAL_TEST.md:
// "Single-turn chat that applies actions".
//
// 💸 COST WARNING — one real LLM call per run. Don't loop in CI without
// mocking; the unit tests in backend/tests/test_ai_views_chat.py and
// backend/tests/test_ai_service_chat.py are the authoritative regression
// nets. This script's value is end-to-end fidelity: real Inertia page,
// real chat-completions request body, real response envelope, real DB
// mutation, real audit row.
//
// Scenario:
//   1. Seed an empty draft schedule on a far-future date with no template
//      auto-draft (so the dock stays focused on chat without the spinner
//      competing with a draft generation).
//   2. Pre-submit assertions:
//        - privacy hint is rendered BEFORE the user types anything
//          (regression-tests iter-5's "always-on" fix)
//        - the input is a <textarea>, NOT the legacy <input>
//        - the `›` prompt marker is visible
//        - status dot has the .healthy class
//        - the chat-thread container is NOT yet rendered (no bubbles)
//   3. Send a concrete apply prompt: "add 30-minute focus block at 10:00".
//   4. Wire-level assertions:
//        - exactly ONE POST /api/ai/schedules/<date>/chat/
//        - request body shape: { messages: [{role:"user", content:string}] }
//          with NO assistant role at this point
//        - response 200 with all four envelope keys
//          {blocks, explanation, ask, applied}
//        - applied=true, ask=null, blocks is an array
//   5. UI assertions:
//        - thread now has ≥2 bubbles (user + assistant)
//        - the user bubble carries the typed text
//   6. DB assertions:
//        - schedule status flipped draft → active
//        - ≥1 TimeBlock now exists for the seeded schedule
//        - latest AIInteraction row: kind=command, success=True,
//          actions_json non-empty, user_command starts with the prompt
//        - ai_response decodes to JSON with keys
//          {transcript_sha256, turn_count, raw} and turn_count==1
//
// Run from frontend/:
//   node scripts/playwright/ai-chat-single-turn-apply.mjs
//
// Pre-reqs:
//   * Django :8006, Vite :5173
//   * Test user `playwright` (see other scripts)
//   * `LLM_API_KEY` set
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY. The seed step truncates the
// target schedule's blocks.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// Test 1's setup section recommends 2026-09-25 (a date with no template
// auto-draft). Distinct from the other chat scripts so concurrent runs
// do not stomp on each other's seed.
const SCHEDULE_DATE = "2026-09-25"
const SCHEDULE_DATE_PARTS = [2026, 9, 25]
const PROMPT = "add 30-minute focus block at 10:00"

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Seeding empty draft schedule via Django shell…")
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
  console.error("\n❌ Seed failed. Is Django running? Does the playwright user exist?")
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

const failures = []
function fail(msg) {
  failures.push(msg)
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

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, {
    waitUntil: "networkidle",
  })

  // ── Pre-submit UI assertions ─────────────────────────────────────────
  console.log("→ Pre-submit UI assertions…")

  const privacyHint = page.locator('[data-testid="chat-privacy-hint"]')
  if (!(await privacyHint.isVisible())) {
    fail("privacy hint not visible before typing (iter-5 always-on regression)")
  } else {
    const hintText = (await privacyHint.textContent()) || ""
    if (!hintText.includes("Full chat history is re-sent")) {
      fail(`privacy hint text unexpected: ${hintText.slice(0, 80)}`)
    }
  }

  const inputEl = page.locator('[data-testid="chat-input"]')
  if (!(await inputEl.isVisible())) {
    fail("chat input not visible")
  } else {
    const tagName = await inputEl.evaluate((el) => el.tagName.toLowerCase())
    if (tagName !== "textarea") {
      fail(`chat input expected <textarea>, got <${tagName}> (legacy regression)`)
    }
    const disabled = await inputEl.isDisabled()
    if (disabled) {
      fail("chat input was disabled before submit")
    }
  }

  const promptMarker = page.locator(".prompt-marker").first()
  if (!(await promptMarker.isVisible())) {
    fail("`›` prompt marker not visible")
  }

  const statusDot = page.locator(".status-dot").first()
  const dotClass = (await statusDot.getAttribute("class")) || ""
  if (!dotClass.includes("healthy")) {
    fail(`status-dot expected .healthy, got class="${dotClass}"`)
  }

  const threadBefore = page.locator('[data-testid="chat-thread"]')
  if ((await threadBefore.count()) > 0) {
    fail("chat-thread container rendered BEFORE first turn (should be hidden until visibleMessages.length > 0)")
  }

  // ── Submit the apply prompt ──────────────────────────────────────────
  console.log(`→ Submitting prompt: ${JSON.stringify(PROMPT)}…`)
  await inputEl.fill(PROMPT)
  await Promise.all([
    page.waitForResponse(
      (resp) => /\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(resp.url()),
      { timeout: 25_000 },
    ),
    inputEl.press("Enter"),
  ])
  // Allow Inertia partial reload + Vue thread state to settle.
  await page.waitForTimeout(800)

  // ── Wire-level assertions ────────────────────────────────────────────
  console.log("→ Wire-level assertions…")
  if (chatCalls.length !== 1) {
    fail(`expected exactly 1 chat call, got ${chatCalls.length}`)
  }
  const call = chatCalls[0]
  let parsedReq = null
  let parsedResp = null
  if (call) {
    if (call.status !== 200) {
      fail(`response expected 200, got ${call.status}`)
    }
    try {
      parsedReq = JSON.parse(call.requestBody)
    } catch {
      fail("request body is not JSON")
    }
    try {
      parsedResp = JSON.parse(call.responseBody)
    } catch {
      fail("response body is not JSON")
    }

    if (parsedReq) {
      if (!Array.isArray(parsedReq.messages)) {
        fail("request body.messages is not an array")
      } else if (parsedReq.messages.length !== 1) {
        fail(`request expected 1 message, got ${parsedReq.messages.length}`)
      } else {
        const m = parsedReq.messages[0]
        if (m.role !== "user") {
          fail(`first message role expected "user", got ${JSON.stringify(m.role)}`)
        }
        if (typeof m.content !== "string" || !m.content.includes("focus block")) {
          fail(`first message content unexpected: ${JSON.stringify(m.content).slice(0, 120)}`)
        }
      }
      // No assistant role at this turn — the iter-1 wire invariant.
      const roles = (parsedReq.messages || []).map((m) => m.role)
      if (roles.includes("assistant")) {
        fail(`request must not include assistant role on turn 1 — got roles ${JSON.stringify(roles)}`)
      }
    }

    if (parsedResp) {
      for (const key of ["blocks", "explanation", "ask", "applied"]) {
        if (!(key in parsedResp)) {
          fail(`response envelope missing key "${key}"`)
        }
      }
      if (parsedResp.applied !== true) {
        fail(`expected applied=true, got applied=${JSON.stringify(parsedResp.applied)} (ask=${JSON.stringify(parsedResp.ask)})`)
      }
      if (parsedResp.ask !== null) {
        fail(`expected ask=null on apply turn, got ${JSON.stringify(parsedResp.ask)}`)
      }
      if (!Array.isArray(parsedResp.blocks) || parsedResp.blocks.length < 1) {
        fail(`expected blocks array with ≥1 entry, got ${JSON.stringify(parsedResp.blocks).slice(0, 200)}`)
      }
    }
  }

  // ── UI assertions after submit ───────────────────────────────────────
  console.log("→ Post-submit UI assertions…")
  const thread = page.locator('[data-testid="chat-thread"]')
  await thread.waitFor({ timeout: 4000 }).catch(() => {})
  const bubbles = thread.locator(".bubble")
  const bubbleCount = await bubbles.count()
  if (bubbleCount < 2) {
    fail(`expected ≥2 bubbles (user + assistant) after apply turn, got ${bubbleCount}`)
  } else {
    const userBubbleText = (await bubbles.nth(0).textContent()) || ""
    if (!userBubbleText.includes("focus block")) {
      fail(`first bubble (user) text unexpected: ${userBubbleText.slice(0, 80)}`)
    }
    const userBubbleClass = (await bubbles.nth(0).getAttribute("class")) || ""
    if (!userBubbleClass.includes("bubble-user")) {
      fail(`first bubble missing .bubble-user class, got "${userBubbleClass}"`)
    }
    const assistantBubbleClass = (await bubbles.nth(1).getAttribute("class")) || ""
    if (!assistantBubbleClass.includes("bubble-assistant")) {
      fail(`second bubble missing .bubble-assistant class, got "${assistantBubbleClass}"`)
    }
  }

  // ── DB assertions ────────────────────────────────────────────────────
  console.log("→ DB assertions…")
  const dbStateOut = execSync(
    `uv run python backend/manage.py shell -c "
import json
from schedules.models import Schedule, TimeBlock
from ai.models import AIInteraction
s = Schedule.objects.get(date='${SCHEDULE_DATE}', user__username='${USERNAME}')
print('STATUS', s.status)
print('BLOCKS', TimeBlock.objects.filter(schedule=s).count())
r = AIInteraction.objects.filter(schedule=s).order_by('-created_at').first()
if r is None:
    print('NO_AI_ROW')
else:
    print('KIND', r.kind)
    print('SUCCESS', r.success)
    print('ACTIONS_LEN', len(r.actions_json))
    print('USER_COMMAND', r.user_command)
    try:
        payload = json.loads(r.ai_response)
        print('AI_RESPONSE_KEYS', sorted(payload.keys()))
        print('TURN_COUNT', payload.get('turn_count'))
        print('HASH_PREFIX', (payload.get('transcript_sha256') or '')[:12])
        print('HAS_RAW', isinstance(payload.get('raw'), str) and len(payload['raw']) > 0)
    except Exception as e:
        print('AI_RESPONSE_PARSE_ERROR', repr(e))
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )

  // Parse line-by-line.
  const dbLines = dbStateOut.trim().split("\n").filter((l) => l.trim() !== "")
  const dbMap = {}
  for (const line of dbLines) {
    const idx = line.indexOf(" ")
    if (idx === -1) {
      dbMap[line] = ""
    } else {
      dbMap[line.slice(0, idx)] = line.slice(idx + 1)
    }
  }

  if (dbMap.STATUS !== "active") {
    fail(`schedule status expected "active" after apply, got ${JSON.stringify(dbMap.STATUS)} (mark_active_on_edit regression?)`)
  }
  const blockCount = Number(dbMap.BLOCKS || "0")
  if (blockCount < 1) {
    fail(`expected ≥1 TimeBlock after apply, got ${blockCount}`)
  }
  if ("NO_AI_ROW" in dbMap) {
    fail("no AIInteraction row created for this schedule")
  } else {
    if (dbMap.KIND !== "command") {
      fail(`AIInteraction.kind expected "command", got ${JSON.stringify(dbMap.KIND)}`)
    }
    if (dbMap.SUCCESS !== "True") {
      fail(`AIInteraction.success expected True, got ${JSON.stringify(dbMap.SUCCESS)}`)
    }
    if (Number(dbMap.ACTIONS_LEN || "0") < 1) {
      fail(`AIInteraction.actions_json expected ≥1 entry, got ${dbMap.ACTIONS_LEN}`)
    }
    if (!(dbMap.USER_COMMAND || "").includes("focus block")) {
      fail(`AIInteraction.user_command unexpected: ${JSON.stringify(dbMap.USER_COMMAND).slice(0, 120)}`)
    }
    const expectedKeys = "['raw', 'transcript_sha256', 'turn_count']"
    if (dbMap.AI_RESPONSE_KEYS !== expectedKeys) {
      fail(`AIInteraction.ai_response keys expected ${expectedKeys}, got ${dbMap.AI_RESPONSE_KEYS}`)
    }
    if (dbMap.TURN_COUNT !== "1") {
      fail(`turn_count expected "1", got ${JSON.stringify(dbMap.TURN_COUNT)}`)
    }
    if (!dbMap.HASH_PREFIX || dbMap.HASH_PREFIX.length < 8) {
      fail(`transcript_sha256 missing or too short: ${JSON.stringify(dbMap.HASH_PREFIX)}`)
    }
    if (dbMap.HAS_RAW !== "True") {
      fail("ai_response.raw missing or empty")
    }
  }

  // ── Diagnostics ─────────────────────────────────────────────────────
  console.log("\n=== Captured chat call ===")
  if (call) {
    console.log(`  status=${call.status}`)
    console.log(`  Request body: ${call.requestBody.slice(0, 300)}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 400)}`)
  }
  console.log("\n=== DB after ===")
  console.log(dbStateOut.trim())

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — Test 1: single-turn chat applies actions end-to-end")
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
