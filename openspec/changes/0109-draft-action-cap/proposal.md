# 0109 — Draft action cap follows the template limit

## Why

Templates may hold 50 blocks, but a draft reply was rejected above 20 actions, the chat cap. A draft emits one add per block, so a 21–50-block template returned a 502 or lost blocks (issue #222). See [docs/features/0109_PLAN.md](../../../docs/features/0109_PLAN.md).

## What changes

- `MAX_TEMPLATE_BLOCKS` moves to the ORM-free `templates_mgr/limits.py` and stays the single source of truth.
- Drafts use `MAX_DRAFT_ACTIONS = MAX_TEMPLATE_BLOCKS + 10` (60). Chat keeps 20.
- The draft system prompt states the cap and tells the model to drop history-derived additions, never template blocks, to stay under it.
- The draft provider call uses a new `LLM_DRAFT_REQUEST_TIMEOUT` (default 60 s); chat keeps `LLM_REQUEST_TIMEOUT`.

## Capabilities

- `ai/draft`: MODIFIED "Draft provider call", "Draft response validation", "Atomic draft apply"; ADDED "Draft action cap covers a full template".
- `ai/config`: MODIFIED "Provider call timeout and failure normalization".
- `ai/chat`: MODIFIED "Reply envelope validation".
- `templates/templates`: MODIFIED "Template block validation".

## Impact

Draft generation only, plus one new setting. No migration, no frontend change, no API shape change.
