# 0104 — Relative-add guard recovery

## Why

A chat clarification from the relative-add guard was a dead end. "add Vocal, then Stretching, then Breakfast. without gap, one after another" was read as "add after a block named *another*"; the guard's question then saved a pending intent with an empty scope, so every answer returned 409 `pending_intent_scope`; and natural clock answers such as "vocal starts at 0945" were not recognized. See [docs/features/0104_PLAN.md](../../../docs/features/0104_PLAN.md).

## What changes

- Sequential idioms ("one after another", "один после другого") are not placement relations.
- A fresh relative-guard question saves one server-derived add permission per interrupted add (known title, category and derivable duration; placement missing).
- A continuation that fails the scope check gets the guard's question instead of 409 when the guard has one and the reply only adds saved, unplaced blocks; nothing is written.
- Natural clock answers resolve an unbound relation or the generic multi-relation time question; a start clause about the new block is not an anchor answer.

## Capabilities

- `ai/chat-mutations`: MODIFIED "Relative add guard".
- `ai/chat-intents`: MODIFIED "Pending intent continuation"; ADDED "Scope for relative-add guard questions" and "Guard question before scope rejection".
- `ai/chat`: MODIFIED "Success response envelope".

## Impact

AI chat turns and server-owned pending intents only. No schema migration, no frontend source change, no change to replay-guard recovery.
