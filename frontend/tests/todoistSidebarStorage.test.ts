import { afterEach, describe, expect, it } from "vitest"
import {
  readTodoistSidebarOpen,
  TODOIST_SIDEBAR_OPEN_KEY,
  writeTodoistSidebarOpen,
} from "../src/utils/todoistSidebarStorage"
import { clearLocalStorage } from "./helpers/storage"

afterEach(() => {
  clearLocalStorage()
})

describe("todoistSidebarStorage", () => {
  it("defaults to open when key is missing", () => {
    expect(readTodoistSidebarOpen()).toBe(true)
  })

  it("persists false", () => {
    writeTodoistSidebarOpen(false)
    expect(localStorage.getItem(TODOIST_SIDEBAR_OPEN_KEY)).toBe("false")
    expect(readTodoistSidebarOpen()).toBe(false)
  })

  it("persists true", () => {
    writeTodoistSidebarOpen(true)
    expect(readTodoistSidebarOpen()).toBe(true)
  })

  it("treats malformed JSON as open", () => {
    localStorage.setItem(TODOIST_SIDEBAR_OPEN_KEY, "not-json")
    expect(readTodoistSidebarOpen()).toBe(true)
  })
})
