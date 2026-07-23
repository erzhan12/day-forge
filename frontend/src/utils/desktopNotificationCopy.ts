import type { SoundEventType, TimeBlock } from "../types"

// English title/body builders for desktop notifications (issue #100). Kept as
// pure functions with no Vue deps so a future i18n pass can swap the lookup in
// one place. `SoundEventType` ("start" | "end") is reused as the event type.

export function desktopNotificationTitle(type: SoundEventType): string {
  return type === "start" ? "Block started" : "Block ended"
}

export function desktopNotificationBody(
  type: SoundEventType,
  block: TimeBlock,
): string {
  return type === "start"
    ? `${block.title} · ${block.start_time}–${block.end_time}`
    : `${block.title} finished`
}
