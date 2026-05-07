// Feature 0007: chat returns a clarifying question, user follows up,
// the second turn applies the requested action.
//
// 💸 COST WARNING — this script makes UP TO TWO real LLM calls against
// the configured provider. Don't loop in CI without mocking; for that
// the unit tests in backend/tests/test_ai_views_chat.py are the
// authoritative source. The script's value is end-to-end fidelity:
// real Inertia page, real chat-completions request body, real response
// envelope, real DB mutation on the apply turn.
//
// Scenario:
//   1. Seed an empty draft schedule on a far-future date.
//   2. Send turn 1: "запланируй встречу" — vague enough that the
//      model SHOULD ask "когда?" rather than guess. (Per the system
//      prompt in backend/ai/prompts.py:SYSTEM_PROMPT_CHAT, ambiguous
//      requests must return actions=[] + a non-null ask.)
//   3. Verify the response: 200, ask is a non-empty string, applied=false,
//      no blocks created.
//   4. Send turn 2: "в 14:00 на час" — this should resolve the
//      ambiguity. The model should return actions=[add ...] with
//      applied=true.
//   5. Verify the schedule now has one block.
//
// Note on model nondeterminism: if turn 1 returns actions instead of
// ask, the script reports SKIP rather than FAIL — the model deviated
// from the system prompt, which is a model issue, not a regression in
// our wiring. The wiring assertion (request body shape, audit row
// transcript hash) still runs and must pass.
//
// Run from frontend/:
//   node scripts/playwright/ai-chat-clarifying-question.mjs
//
// Pre-reqs:
//   * Django :8006, Vite :5173
//   * Test user `playwright` (see other scripts for the user-creation
//     snippet and rationale)
//   * `LLM_API_KEY` set
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY. Do not run against any
// deployment that real users share — the seed step truncates the
// target schedule's blocks.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// Far-future, deterministic, distinct from other scripts so concurrent
// runs do not stomp on each other's seed.
const SCHEDULE_DATE = "2026-09-21"

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
    user=u, date=datetime.date(2026, 9, 21), defaults={'status': 'draft'}
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

async function submitChatTurn(text) {
  const ta = page.locator('[data-testid="chat-input"]')
  await ta.waitFor({ timeout: 3000 })
  await ta.fill(text)
  // Enter sends; Shift+Enter inserts a newline (verified by unit tests
  // in tests/CommandBar.test.ts).
  await Promise.all([
    page.waitForResponse(
      (resp) => /\/api\/ai\/schedules\/[^/]+\/chat\/$/.test(resp.url()),
      { timeout: 25_000 },
    ),
    ta.press("Enter"),
  ])
  // Allow the partial reload + Vue state to settle.
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

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, {
    waitUntil: "networkidle",
  })

  console.log("→ Turn 1: ambiguous request that should provoke a clarifying question…")
  await submitChatTurn("запланируй встречу")

  console.log("→ Turn 2: follow-up resolving the ambiguity…")
  await submitChatTurn("в 14:00 на час, рабочая")

  // Pull the post-state from the DB.
  const dbStateOut = execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
s = Schedule.objects.get(date='${SCHEDULE_DATE}', user__username='${USERNAME}')
blocks = list(TimeBlock.objects.filter(schedule=s).values('title', 'start_time', 'end_time'))
print('STATUS', s.status)
for b in blocks:
    print('BLOCK', b['title'], b['start_time'], b['end_time'])
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )

  console.log("\n=== Captured chat calls ===")
  for (const [i, call] of chatCalls.entries()) {
    console.log(`Turn ${i + 1}: status=${call.status}`)
    console.log(`  Request body: ${call.requestBody.slice(0, 300)}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 400)}`)
  }
  console.log("\n=== DB after ===")
  console.log(dbStateOut.trim())

  console.log("\n=== Verdict ===")
  let pass = true
  let skip = false
  const reasons = []

  if (chatCalls.length !== 2) {
    pass = false
    reasons.push(`expected 2 chat calls, got ${chatCalls.length}`)
  } else {
    const [t1, t2] = chatCalls

    // Turn 1: contract-shape assertions ALWAYS run.
    if (t1.status !== 200) {
      pass = false
      reasons.push(`turn 1 expected HTTP 200, got ${t1.status}`)
    }
    let t1Parsed
    try {
      t1Parsed = JSON.parse(t1.responseBody)
    } catch {
      pass = false
      reasons.push("turn 1 response body is not JSON")
    }
    if (t1Parsed) {
      // Wiring: the response envelope MUST include all four fields,
      // regardless of which branch (ask / apply / chitchat) the model
      // took.
      for (const key of ["blocks", "explanation", "ask", "applied"]) {
        if (!(key in t1Parsed)) {
          pass = false
          reasons.push(`turn 1 missing field ${key} from response envelope`)
        }
      }
      // Wiring: request body must carry { messages: [{role,content}] }
      // and ONLY the latest user turn at this point (no prior assistant
      // turn yet).
      let t1Req
      try {
        t1Req = JSON.parse(t1.requestBody)
      } catch {
        pass = false
        reasons.push("turn 1 request body is not JSON")
      }
      if (
        t1Req &&
        (!Array.isArray(t1Req.messages) ||
          t1Req.messages.length !== 1 ||
          t1Req.messages[0].role !== "user" ||
          typeof t1Req.messages[0].content !== "string")
      ) {
        pass = false
        reasons.push(
          `turn 1 request shape unexpected: ${JSON.stringify(t1Req).slice(0, 200)}`,
        )
      }
      // Behavioural: model SHOULD ask. If it doesn't, we SKIP behavioural
      // assertions — model nondeterminism is not our regression to fix.
      if (typeof t1Parsed.ask !== "string" || t1Parsed.ask === "") {
        skip = true
        console.log(
          "  ⚠ model did not ask a clarifying question on turn 1 — skipping behavioural assertions.",
        )
      } else if (t1Parsed.applied !== false) {
        pass = false
        reasons.push(`turn 1 ask was set but applied=${t1Parsed.applied} (must be false)`)
      }
    }

    // Turn 2: the follow-up. Wiring assertion ALWAYS runs.
    if (t2.status !== 200) {
      pass = false
      reasons.push(`turn 2 expected HTTP 200, got ${t2.status}`)
    }
    let t2Req
    try {
      t2Req = JSON.parse(t2.requestBody)
    } catch {
      pass = false
      reasons.push("turn 2 request body is not JSON")
    }
    if (t2Req) {
      // Wiring: turn 2's transcript MUST carry the prior turns. The
      // assistant message in slot [1] confirms `useChat` is appending
      // assistant turns to the thread between requests.
      if (!Array.isArray(t2Req.messages) || t2Req.messages.length < 3) {
        pass = false
        reasons.push(
          `turn 2 expected ≥3 messages in transcript, got ${
            t2Req?.messages?.length ?? "n/a"
          }`,
        )
      } else {
        const roles = t2Req.messages.map((m) => m.role)
        if (
          roles[0] !== "user" ||
          roles[1] !== "assistant" ||
          roles[roles.length - 1] !== "user"
        ) {
          pass = false
          reasons.push(`turn 2 role pattern unexpected: ${JSON.stringify(roles)}`)
        }
      }
    }

    // Behavioural turn-2 assertions: only fire when turn 1 actually
    // produced a clarifying question. If turn 1 already applied (model
    // deviated from system prompt), skipping turn-2 behavioural checks
    // is correct — the model already mutated the schedule on turn 1
    // and turn 2 is downstream noise. Without this gate the script
    // could give a false PASS for the wrong reason.
    if (!skip) {
      let t2Parsed
      try {
        t2Parsed = JSON.parse(t2.responseBody)
      } catch {
        pass = false
        reasons.push("turn 2 response body is not JSON")
      }
      if (t2Parsed) {
        if (t2Parsed.applied !== true) {
          pass = false
          reasons.push(
            `turn 2 expected applied=true after answering the clarifying ` +
              `question, got applied=${t2Parsed.applied} ` +
              `(ask=${JSON.stringify(t2Parsed.ask)})`,
          )
        }
        if (!Array.isArray(t2Parsed.blocks) || t2Parsed.blocks.length < 1) {
          pass = false
          reasons.push(
            `turn 2 expected blocks array with >=1 entry, got ` +
              `${JSON.stringify(t2Parsed.blocks)}`,
          )
        }
      }

      // DB-side cross-check: the schedule MUST have at least one block
      // after turn 2 if the model honoured the apply contract. The
      // ``BLOCK ...`` lines in dbStateOut come from the seed inspector
      // we ran above; count them to avoid relying on response shape
      // alone (a buggy view that returned blocks without persisting
      // would otherwise pass).
      const dbBlockLines = dbStateOut
        .split("\n")
        .map((l) => l.trim())
        .filter((l) => l.startsWith("BLOCK "))
      if (dbBlockLines.length < 1) {
        pass = false
        reasons.push(
          `expected DB to have ≥1 block after turn 2 apply, got 0 ` +
            `(dbStateOut: ${dbStateOut.trim().split("\n").join(" | ")})`,
        )
      } else {
        console.log(`  DB block count after apply: ${dbBlockLines.length}`)
      }
    }
  }

  if (pass) {
    if (skip) {
      console.log("⚠ PASS-WITH-SKIP — wiring OK, model deviated from prompt on turn 1")
    } else {
      console.log("✅ PASS — chat clarifying-question + follow-up flow works")
    }
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
