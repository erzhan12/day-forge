# 0102 — Refine the block just added

## Why

After a successful add, a follow-up that only gives a time, duration or category ("в 14:00 на час, рабочая") was prefixed with "add" and then blocked by the replay guard, so the user could not refine the block they had just created. See issue #226 and [docs/features/0102_PLAN.md](../../../../docs/features/0102_PLAN.md).

## What changes

- The implicit add rewrite leaves a time or duration fragment that follows an assistant reply unchanged.
- The chat prompt resolves such a fragment to an existing block and updates only the requested fields; an ambiguous target gets a question.
- The replay guard is unchanged: duplicate adds are still rejected.

## Capabilities

- `ai/chat-mutations`: MODIFIED "Implicit add rewrite" (attribute follow-up after an assistant reply is sent as typed); ADDED "Refine the block just added".

## Impact

Chat turns only. Draft generation and the replay guard boundaries are unchanged.
