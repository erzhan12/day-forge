// Feature 0009 follow-up — Playwright coverage for /command/ endpoint
// (claude-review PR #22 iter-1 P2 [TESTING] gap).
//
// 💸 COST WARNING — one real LLM call per run. Don't loop in CI without
// mocking; the unit tests in backend/tests/ are the authoritative
// regression nets. This script's value is end-to-end fidelity: real
// Inertia login, real CSRF cookie, real chat-completions request body,
// real DB mutation, real audit row, real status promotion.
//
// /command/ has no UI driver in the current frontend — useAI.ts is
// deprecated and not imported. We log in via the real UI to acquire a
// session + XSRF-TOKEN cookie, then POST to the endpoint via
// page.evaluate(fetch) so credentials and CSRF are auto-attached.
//
// Scenario:
//   1. Seed an empty draft schedule on 2027-01-15 (weekday).
//   2. UI login → navigate to the seeded date.
//   3. Direct-POST /command/ with a deterministic add-block prompt.
//   4. Wire-level assertions: status 200, body {blocks, explanation}
//      (no `ask`, no `applied` — those are chat-only keys).
//   5. DB assertions: ≥1 TimeBlock; category in VALID_CATEGORIES;
//      latest AIInteraction row has kind=command, success=True,
//      actions_json non-empty, user_command starts with the prompt;
//      schedule.status flipped draft → active.
//
// Run from frontend/:
//   node scripts/playwright/ai-command-add-block.mjs
//
// Pre-reqs:
//   * Django :8006, Vite :5173
//   * Test user `playwright`
//   * `LLM_API_KEY` set
//
// Concurrency: run this script SERIALLY with the other ai-*.mjs scripts.
// They share the `playwright` user and the `ai_cmd_rl` / `ai_draft_rl`
// rate-limit counters, so parallel execution will race on the counters
// and may produce false failures in the 409 script's "no consumption"
// assertion. Different seed dates prevent DB conflicts; the shared
// counters do not.
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY. The seed step truncates the
// target schedule's blocks.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// Unique 2027-Q1 weekday date not used by any existing script.
const SCHEDULE_DATE = "2027-01-15"
const SCHEDULE_DATE_PARTS = [2027, 1, 15]
const PROMPT = "add a 30-minute focus block at 10:00"
const VALID_CATEGORIES = ["work", "personal", "health", "other"]

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Pre-flight: confirming playwright user exists…")
try {
  const preflight = execSync(
    `uv run python backend/manage.py shell -c "
from django.contrib.auth.models import User
print('EXISTS', User.objects.filter(username='${USERNAME}').exists())
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )
  if (!preflight.includes("EXISTS True")) {
    console.error("\n❌ playwright user is missing. Run:")
    console.error("   uv run python backend/manage.py createsuperuser")
    console.error(`   (use username '${USERNAME}' / password '${PASSWORD}')`)
    process.exit(2)
  }
} catch (err) {
  console.error("\n❌ Pre-flight shell failed:", err.message)
  process.exit(2)
}

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
  console.error("\n❌ Seed failed. Is Django running?")
  console.error(err.message)
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
})
const page = await context.newPage()

const commandCalls = []
page.on("response", async (resp) => {
  const url = resp.url()
  if (/\/api\/ai\/schedules\/[^/]+\/command\/$/.test(url)) {
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
    commandCalls.push({
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

  console.log("→ Direct-POST /command/ via page.evaluate(fetch)…")
  const postResult = await page.evaluate(
    async ({ url, prompt }) => {
      const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
      const csrf = match ? decodeURIComponent(match[1]) : ""
      if (!csrf) {
        return { error: "no XSRF-TOKEN cookie present" }
      }
      const r = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "content-type": "application/json",
          "x-xsrf-token": csrf,
        },
        body: JSON.stringify({ command: prompt }),
      })
      return { status: r.status, body: await r.text() }
    },
    {
      url: `${BASE}/api/ai/schedules/${SCHEDULE_DATE}/command/`,
      prompt: PROMPT,
    },
  )
  // Give Inertia/Vue a beat in case any side-channel listeners are firing.
  await page.waitForTimeout(400)

  console.log("→ Wire-level assertions…")
  if (postResult.error) {
    fail(`fetch precondition error: ${postResult.error}`)
  }
  if (postResult.body && postResult.body.includes("SynchronousOnlyOperation")) {
    fail(
      "ASYNC REGRESSION: response body contains 'SynchronousOnlyOperation' — " +
        "missed await request.auser() or sync ORM call in async path",
    )
  }
  if (commandCalls.length !== 1) {
    fail(`expected exactly 1 /command/ call, got ${commandCalls.length}`)
  }
  const call = commandCalls[0]
  let parsedResp = null
  if (!call) {
    // Skip the rest of the wire-level block if no call was captured;
    // the count assertion above already recorded the failure, and
    // dereferencing `call.*` would crash the aggregator before the
    // verdict line runs.
  } else {
    if (call.status !== 200) {
      fail(`response expected 200, got ${call.status}; body=${call.responseBody.slice(0, 300)}`)
    } else {
      try {
        parsedResp = JSON.parse(call.responseBody)
      } catch {
        fail("response body is not JSON")
      }
      if (parsedResp) {
        if (!Array.isArray(parsedResp.blocks)) {
          fail(`response.blocks expected array, got ${typeof parsedResp.blocks}`)
        }
        if (typeof parsedResp.explanation !== "string") {
          fail(`response.explanation expected string, got ${typeof parsedResp.explanation}`)
        }
        // /command/ envelope must NOT include chat-only keys.
        if ("ask" in parsedResp) {
          fail(`response envelope must not include "ask" key (chat-only)`)
        }
        if ("applied" in parsedResp) {
          fail(`response envelope must not include "applied" key (chat-only)`)
        }
      }
      let parsedReq = null
      try {
        parsedReq = JSON.parse(call.requestBody)
      } catch {
        fail("request body is not JSON")
      }
      if (parsedReq && parsedReq.command !== PROMPT) {
        fail(`request.command expected ${JSON.stringify(PROMPT)}, got ${JSON.stringify(parsedReq.command)}`)
      }
    }
  }

  console.log("→ DB assertions…")
  const dbStateOut = execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from ai.models import AIInteraction
s = Schedule.objects.get(date='${SCHEDULE_DATE}', user__username='${USERNAME}')
print('STATUS', s.status)
print('BLOCKS', TimeBlock.objects.filter(schedule=s).count())
for b in TimeBlock.objects.filter(schedule=s).order_by('start_time'):
    print('BLOCK', b.category, b.start_time, b.end_time)
r = AIInteraction.objects.filter(schedule=s).order_by('-created_at').first()
if r is None:
    print('NO_AI_ROW')
else:
    print('KIND', r.kind)
    print('SUCCESS', r.success)
    print('ACTIONS_LEN', len(r.actions_json))
    print('USER_COMMAND', r.user_command)
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )

  const dbLines = dbStateOut.trim().split("\n").filter((l) => l.trim() !== "")
  const dbMap = {}
  const blockRows = []
  for (const line of dbLines) {
    const idx = line.indexOf(" ")
    const key = idx === -1 ? line : line.slice(0, idx)
    const rest = idx === -1 ? "" : line.slice(idx + 1)
    if (key === "BLOCK") {
      blockRows.push(rest)
    } else {
      dbMap[key] = rest
    }
  }

  if (dbMap.STATUS !== "active") {
    fail(`schedule.status expected "active" after non-empty apply, got ${JSON.stringify(dbMap.STATUS)}`)
  }
  const blockCount = Number(dbMap.BLOCKS || "0")
  if (blockCount < 1) {
    fail(`expected ≥1 TimeBlock after apply, got ${blockCount}`)
  }
  for (const row of blockRows) {
    const [category] = row.split(" ")
    if (!VALID_CATEGORIES.includes(category)) {
      fail(`block has invalid category ${JSON.stringify(category)}; allowed: ${VALID_CATEGORIES.join(",")}`)
    }
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
    if (!(dbMap.USER_COMMAND || "").includes(PROMPT)) {
      fail(`AIInteraction.user_command expected to contain the full prompt, got ${JSON.stringify(dbMap.USER_COMMAND).slice(0, 120)}`)
    }
  }

  console.log("\n=== Captured /command/ call ===")
  if (call) {
    console.log(`  status=${call.status}`)
    console.log(`  Request body: ${call.requestBody.slice(0, 300)}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 400)}`)
  }
  console.log("\n=== page.evaluate(fetch) result ===")
  console.log(`  status=${postResult.status} body=${(postResult.body || "").slice(0, 300)}`)
  console.log("\n=== DB after ===")
  console.log(dbStateOut.trim())

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — /command/ happy path: status flip + audit row + DB mutation end-to-end")
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
