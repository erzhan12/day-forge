import type { UndoAction } from "../types"

/** Canonical toast copy for delete, move and add on the Dark 4a phone (feature 0113). */
export const MOBILE_TOAST_COPY = {
  delete: "Block deleted",
  add: "Block added",
  drag: "Block moved",
} as const

export function undoNotice(
  mobile: boolean,
  type: keyof typeof MOBILE_TOAST_COPY,
  desktopDescription: string,
): Pick<UndoAction, "description" | "type" | "silent"> {
  if (mobile) return { description: MOBILE_TOAST_COPY[type], type, silent: false }
  return { description: desktopDescription, type, silent: true }
}
