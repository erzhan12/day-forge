import { describe, expect, it } from "vitest"
import { undoNotice } from "../src/utils/mobileUndo"

describe("undoNotice (feature 0113)", () => {
  it("keeps the desktop description silent", () => {
    expect(undoNotice(false, "delete", 'Deleted "Gym"')).toEqual({
      description: 'Deleted "Gym"', type: "delete", silent: true,
    })
    expect(undoNotice(false, "add", 'Added "Gym"')).toEqual({
      description: 'Added "Gym"', type: "add", silent: true,
    })
    expect(undoNotice(false, "drag", 'Moved "Gym" to 11:00')).toEqual({
      description: 'Moved "Gym" to 11:00', type: "drag", silent: true,
    })
  })

  it("uses the canonical mobile copy and is not silent", () => {
    expect(undoNotice(true, "delete", 'Deleted "Gym"')).toEqual({
      description: "Block deleted", type: "delete", silent: false,
    })
    expect(undoNotice(true, "add", 'Added "Gym"')).toEqual({
      description: "Block added", type: "add", silent: false,
    })
    expect(undoNotice(true, "drag", 'Moved "Gym" to 11:00')).toEqual({
      description: "Block moved", type: "drag", silent: false,
    })
  })
})
