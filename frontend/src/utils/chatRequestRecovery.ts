/** One frozen request per account/day in this tab, until its outcome is known. */
export interface PendingChatRequest {
  date: string
  userId?: number
  body: {
    request_id: string
    expected_revision: number
    pending_intent_id?: string
    pending_intent_version?: number
    intent_action?: "continue" | "cancel" | "new"
    messages: Array<{ role: string; content: string; is_ask?: boolean; is_error?: boolean; applied_add_block_ids?: number[] }>
  }
}

const prefix = "day-forge:chat-request:"
function key(userId: number, date: string) { return `${prefix}${userId}:${date}` }

export function storeChatRequest(request: PendingChatRequest): boolean {
  // Standalone composable owners without an authenticated user are test seams.
  if (request.userId === undefined) return true
  try {
    sessionStorage.setItem(key(request.userId, request.date), JSON.stringify(request))
    return true
  } catch { return false }
}

export function readChatRequest(userId: number | undefined, date: string): PendingChatRequest | null {
  if (userId === undefined) return null
  try {
    const raw = sessionStorage.getItem(key(userId, date))
    if (!raw) return null
    const value = JSON.parse(raw) as PendingChatRequest
    if (value.userId !== userId || value.date !== date || typeof value.body?.request_id !== "string"
      || !Number.isSafeInteger(value.body.expected_revision) || !Array.isArray(value.body.messages)
      || !value.body.messages.every(m => ["user", "assistant"].includes(m.role) && typeof m.content === "string")) return null
    const { pending_intent_id: intentId, pending_intent_version: version, intent_action: action } = value.body
    if (action !== undefined && !["new", "continue", "cancel"].includes(action)) return null
    if (intentId !== undefined || version !== undefined || action === "continue" || action === "cancel") {
      if (typeof intentId !== "string" || !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(intentId)
        || typeof version !== "number" || !Number.isSafeInteger(version) || version < 1) return null
    }
    return value
  } catch { return null }
}

export function removeChatRequest(request: PendingChatRequest): void {
  if (request.userId === undefined) return
  try {
    const stored = readChatRequest(request.userId, request.date)
    if (stored?.body.request_id === request.body.request_id) sessionStorage.removeItem(key(request.userId, request.date))
  } catch { /* An unavailable store must not change an already-known result. */ }
}

export function clearChatRequests(userId: number | undefined): void {
  if (userId === undefined) return
  try {
    for (const name of Object.keys(sessionStorage)) {
      if (name.startsWith(`${prefix}${userId}:`)) sessionStorage.removeItem(name)
    }
  } catch { /* Session reset still clears all in-memory state. */ }
}

export function retainChatRequestsForUser(userId: number | null): void {
  try {
    for (const name of Object.keys(sessionStorage)) {
      if (name.startsWith(prefix) && (userId === null || !name.startsWith(`${prefix}${userId}:`))) sessionStorage.removeItem(name)
    }
  } catch { /* The root still enforces the account boundary in memory. */ }
}
