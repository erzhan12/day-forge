import { afterEach, describe, expect, it } from "vitest"
import {
  readExternalTasksSidebarOpen,
  EXTERNAL_TASKS_SIDEBAR_OPEN_KEY,
  writeExternalTasksSidebarOpen,
} from "../src/utils/externalTasksSidebarStorage"
import { clearLocalStorage } from "./helpers/storage"

afterEach(() => {
  clearLocalStorage()
})

describe("externalTasksSidebarStorage", () => {
  it("defaults to open when key is missing", () => {
    expect(readExternalTasksSidebarOpen()).toBe(true)
  })

  it("persists false", () => {
    writeExternalTasksSidebarOpen(false)
    expect(localStorage.getItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY)).toBe("false")
    expect(readExternalTasksSidebarOpen()).toBe(false)
  })

  it("persists true", () => {
    writeExternalTasksSidebarOpen(true)
    expect(readExternalTasksSidebarOpen()).toBe(true)
  })

  it("treats malformed JSON as open", () => {
    localStorage.setItem(EXTERNAL_TASKS_SIDEBAR_OPEN_KEY, "not-json")
    expect(readExternalTasksSidebarOpen()).toBe(true)
  })
})
