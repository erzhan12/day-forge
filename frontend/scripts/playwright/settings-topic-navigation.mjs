// Feature 0056 — Settings topic navigation smoke.
// Covers desktop/mobile navigation, hash history, sticky desktop nav, and
// preservation of an available disconnected integration form draft.

import { chromium } from "@playwright/test"
import { BASE, login, preflight } from "./test-utils.mjs"

await preflight()

const browser = await chromium.launch({ headless: true })

async function expectSingleVisibleTopic(page, id) {
  const visible = page.locator("[data-settings-topic]:not([hidden])")
  if ((await visible.count()) !== 1) {
    throw new Error(`Expected one visible Settings topic, found ${await visible.count()}`)
  }
  if ((await visible.first().getAttribute("data-settings-topic")) !== id) {
    throw new Error(`Expected visible topic ${id}`)
  }
}

try {
  const desktop = await browser.newContext({ viewport: { width: 1280, height: 700 } })
  const page = await desktop.newPage()
  await login(page)
  await page.goto(`${BASE}/settings/`, { waitUntil: "networkidle" })

  const nav = page.locator('nav[aria-label="Settings topics"]')
  await nav.waitFor({ state: "visible" })
  if ((await page.locator("#settings-topic-select").count()) !== 0) {
    throw new Error("Mobile topic select rendered at desktop width")
  }
  if ((await nav.locator('a[aria-current="page"]').getAttribute("href")) !== "#appearance") {
    throw new Error("Appearance was not the default topic")
  }
  await expectSingleVisibleTopic(page, "appearance")

  await nav.locator('a[href="#integrations"]').click()
  await page.waitForURL(/#integrations$/)
  await expectSingleVisibleTopic(page, "integrations")

  const draftInputs = page.locator(
    '[data-testid="settings-integration-apple"] input[type="email"], ' +
    '[data-testid="settings-integration-todoist"] input[type="password"], ' +
    '[data-testid="settings-integration-habitica"] input[type="text"]',
  )
  if ((await draftInputs.count()) > 0) {
    const draft = draftInputs.first()
    await draft.fill("settings-draft")
    await nav.locator('a[href="#notifications"]').click()
    await nav.locator('a[href="#integrations"]').click()
    if ((await draft.inputValue()) !== "settings-draft") {
      throw new Error("Integration form draft was lost across topic switches")
    }
  }

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  const navTop = (await nav.boundingBox())?.y
  if (navTop === undefined || navTop < 18 || navTop > 32) {
    throw new Error(`Desktop nav did not stay sticky near the top (y=${navTop})`)
  }

  await nav.locator('a[href="#templates-rules"]').click()
  await page.waitForURL(/#templates-rules$/)
  await page.goBack()
  await page.waitForURL(/#integrations$/)
  await expectSingleVisibleTopic(page, "integrations")
  await page.goForward()
  await page.waitForURL(/#templates-rules$/)
  await expectSingleVisibleTopic(page, "templates-rules")
  await desktop.close()

  const mobile = await browser.newContext({ viewport: { width: 390, height: 800 } })
  const mobilePage = await mobile.newPage()
  await login(mobilePage)
  await mobilePage.goto(`${BASE}/settings/`, { waitUntil: "networkidle" })
  if ((await mobilePage.locator('nav[aria-label="Settings topics"]').count()) !== 0) {
    throw new Error("Desktop topic nav rendered at mobile width")
  }
  const select = mobilePage.locator("#settings-topic-select")
  await select.waitFor({ state: "visible" })
  await mobilePage.locator('label[for="settings-topic-select"]').waitFor()
  await select.selectOption("templates-rules")
  await mobilePage.waitForURL(/#templates-rules$/)
  await expectSingleVisibleTopic(mobilePage, "templates-rules")
  await mobile.close()

  console.log("\n✅ Settings topic navigation smoke passed.")
} catch (error) {
  console.error("\n❌ Settings topic navigation smoke failed.")
  console.error(error.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
