# plan-review-loop — design spec

**Date:** 2026-05-22
**Status:** approved by user, ready for implementation planning
**Related skill:** mirrors `~/.claude/skills/plan-debate/` with the planning phase removed.

## Problem

The existing `plan-debate` skill produces a fresh `docs/features/NNNN_PLAN.md` through an adversarial Planner/Reviewer loop. The user often already has a written plan and wants the same adversarial-review discipline applied to it — without re-creating the file. There is currently no skill that takes an existing plan and iterates Reviewer ↔ Planner until convergence.

## Goal

Add a new global skill at `~/.claude/skills/plan-review-loop/` that:

1. Accepts an existing plan file path via `/plan-review-loop <path/to/PLAN.md>`.
2. Runs two independent sub-agents (Reviewer, Planner) in a structured loop, mutating the existing file in place.
3. Terminates on zero open findings (SUCCESS) or 10 iterations (FAILURE), with the same anti-bias α-history discipline as `plan-debate`.

## Non-goals

- No file creation. The plan file must already exist.
- No clarifying-questions flow. Plan content is assumed to be the source of truth; ambiguity is a finding for the Reviewer to raise, not a question for the user.
- No configurable iteration cap in v1. Fixed at 10.
- No on-disk per-iteration artifacts (no `REVIEW.md`). State lives in conversation memory only.

## Command interface

```
/plan-review-loop <path-to-PLAN.md>
```

- Exactly one positional argument: path to an existing markdown plan file.
- Resolved relative to the current working directory if not absolute.

## File layout

```
~/.claude/skills/plan-review-loop/
├── SKILL.md       # orchestrator
├── reviewer.md    # Reviewer sub-agent system prompt (verbatim copy of plan-debate/reviewer.md)
└── planner.md     # Planner sub-agent system prompt (Mode B only — see § Planner)
```

## Setup phase (orchestrator)

1. Parse `plan_path` from the user invocation. If empty → FAILURE with a usage hint.
2. Run `test -f <plan_path>`. If missing → FAILURE: "Plan file does not exist: <path>. /plan-review-loop requires an existing plan; use /plan-debate to create one from scratch."
3. Run `wc -l <plan_path>`. If < 10 lines, emit a warning ("plan looks suspiciously short — proceeding anyway") but do not block.
4. Resolve `plan_format_spec`:
   - If `./commands/plan_feature.md` exists in the project, load its content.
   - Otherwise leave empty — Reviewer will use its embedded canonical spec.
5. Load `reviewer.md` and `planner.md` into memory. They are prepended to every Agent call for their respective role.

## Iteration loop

State held in orchestrator memory:

- `open_findings: dict[id -> finding]` — starts empty.
- `prior_responses: list[response]` — Planner responses from the previous iteration; passed forward to the next Reviewer call so it can adjudicate `author_response`.
- `prior_findings_history: list[finding-with-status]` — every finding ever raised, with its current status and Planner response.
- `plan_hash` — content hash of `<plan_path>` after the last orchestrator-observed snapshot. Used by the diff guard.

Loop `iter` from `1` to `10` inclusive.

### Step A — Reviewer

Always runs first in every iteration (including iter 1).

```
Agent(
  description="plan-review-loop Reviewer iter <iter>",
  subagent_type="general-purpose",
  model="opus",
  prompt=<reviewer.md content> + "\n\n---\n\n## Orchestrator input\n\n"
       + "<plan_path>" + plan_path + "</plan_path>\n"
       + "<iter>" + iter + "</iter>\n"
       + "<your_prior_findings>\n" + json(prior_findings_history) + "\n</your_prior_findings>\n"
)
```

In iter 1, `your_prior_findings = []`.

Parse the JSON response (retry-once on malformed JSON — same policy as `plan-debate`). Update `open_findings`:

- `closed_by_fix` or `closed_by_rationale` → remove from `open_findings`.
- `still_open` → keep.
- For each id still in `open_findings` but not present in `prior_findings_status` → keep, flag `omitted_by_reviewer=true` (failsafe).
- For each entry in `new_findings` → add to `open_findings` with Reviewer-assigned id.

If `open_findings == {}` → **SUCCESS**. Emit:
- path to `plan_path`
- iteration count
- one-paragraph summary (synthesised from Reviewer approval rationales)
- trace summary (see § Trace summary)

Then stop.

### Step B — Planner (revision)

Only runs if `open_findings != {}` and `iter < 10`.

```
Agent(
  description="plan-review-loop Planner iter <iter>",
  subagent_type="general-purpose",
  model="opus",
  prompt=<planner.md content> + "\n\n---\n\n## Orchestrator input\n\n"
       + "<plan_path>" + plan_path + "</plan_path>\n"
       + "<open_findings>\n" + json(open_findings_list) + "\n</open_findings>\n"
       + "<your_prior_rebuttals>\n" + json(prior_rebuttals) + "\n</your_prior_rebuttals>\n"
)
```

Parse the response (retry-once on malformed JSON). Each response has `action ∈ {"fixed", "rebutted"}` with a structured note. The Planner mutates `<plan_path>` via the **Edit** tool (the file already exists; no Write).

### Step C — Diff guard

After Planner returns:

```
git -C <project_root> diff -- <plan_path>
```

For each response with `action="fixed"`: if diff against the last-iteration hash is empty for the relevant section, flag `claimed_fixed_no_diff=true` on that finding. On the next Reviewer call, append to that finding's `note`: "Orchestrator note: author claimed fixed but PLAN.md diff is empty for this section."

If `git` is unavailable or the file is not tracked, skip the diff guard silently (Reviewer remains ultimate authority).

Update `plan_hash` to the file's new content hash. Store responses as `prior_responses` for the next Reviewer call.

## Termination

- **SUCCESS** — any iteration with `open_findings == {}` after Reviewer step. Emit path, iter count, summary, trace.
- **FAILURE at iter > 10** with non-empty `open_findings` — emit:
  - path to `<plan_path>` (mutated in place; user can inspect or revert via git)
  - list of unresolved findings (`id, severity, issue, last status`)
  - latest Planner rebuttal text for each `still_open + rebutted` finding
  - `divergence_signal`: findings that ping-ponged between `rebutted` and `still_open` for ≥3 iterations
  - User prompt: "Accept plan as-is, continue manually, or revert?"
  - Trace summary.
  Then stop. Do NOT auto-loop further.
- **Malformed JSON, second failure (either agent)** — FAILURE with raw output. Stop.
- **Reviewer in iter 1 returns no findings** — SUCCESS in iter 1 (legitimate; plan was already clean).

## Anti-bias invariants (α-history discipline)

Same as `plan-debate`:

- Do NOT pass the Reviewer's free-text reasoning into the Planner's prompt — only the structured `open_findings` list.
- Do NOT pass the Planner's free-text reasoning into the Reviewer's prompt — only the structured prior `author_response` field.
- The two agents communicate exclusively through structured JSON; the orchestrator is the only place that knows both sides.

## Reviewer sub-agent (`reviewer.md`)

**Verbatim copy of `~/.claude/skills/plan-debate/reviewer.md`.** The Reviewer's contract is plan-shape-agnostic — it reviews whatever it is pointed at. No changes needed.

## Planner sub-agent (`planner.md`)

Adapted from `~/.claude/skills/plan-debate/planner.md` with:

1. **Mode A (initial plan creation) removed entirely.** No `<feature_description>`, no `<spec_content>`, no clarifying questions, no Write tool invocation.
2. **Only Mode B (revision) preserved**, with the file-creation pathway stripped:
   - Input: `<plan_path>`, `<open_findings>`, `<your_prior_rebuttals>`.
   - Tool: **Edit** (not Write). The file exists; the Planner mutates it.
   - Output: same JSON envelope as `plan-debate`'s Mode B — list of responses with `id`, `action ∈ {"fixed","rebutted"}`, `note`, and optional `edit_summary`.
3. **Output-discipline guardrails** carried over verbatim from `plan-debate`/planner.md (no streaming text outside the JSON block, JSON-only return).

## Key differences from `plan-debate` (summary)

| Aspect | `plan-debate` | `plan-review-loop` |
|---|---|---|
| Plan file | Creates `docs/features/NNNN_PLAN.md` | Operates on user-supplied existing file |
| File numbering | Auto-numbered | N/A — path given in command |
| Iter 1 | Planner (creates plan) | Reviewer (reviews existing plan) |
| Planner Mode A (initial) | Present (with clarifying-questions sub-flow) | Removed |
| Planner Mode B (revision) | Present | Present (only mode) |
| Planner tool | Write (iter 0) + Edit (iter 1+) | Edit only |
| Clarifying-questions flow | Yes | No |
| Iteration cap | 10 | 10 |
| Anti-bias discipline | α-history | α-history (unchanged) |
| Diff guard | Yes | Yes (unchanged) |
| Reviewer prompt | `reviewer.md` | Verbatim copy of `reviewer.md` |

## Risks / open questions

- **Pathological plans**: a malformed or trivially-short plan file may trigger a finding storm in iter 1. Mitigated by the `wc -l < 10` warning at setup; the user sees the warning before tokens burn. No hard block — user may have a legitimate short stub.
- **Reviewer divergence on subjective findings**: if Reviewer keeps re-opening a finding the Planner reasonably rebutted, the iteration cap stops the spin and surfaces it as a `divergence_signal` for user adjudication. Same mechanism as `plan-debate`.
- **Git-untracked plan files**: diff guard silently no-ops; Reviewer remains the authority. Acceptable trade-off; the diff guard is a hint, not a gate.

## Testing strategy (smoke tests)

After implementation:

1. **T1 — clean plan**: point at a plan known to be high-quality. Expect SUCCESS in iter 1 (zero findings).
2. **T2 — flawed plan**: point at a plan with deliberate gaps (missing tests, vague API surface). Expect 2–4 iterations to converge.
3. **T3 — rebuttal path**: point at a plan where one finding is genuinely a non-issue. Expect Planner to rebut, Reviewer to `closed_by_rationale`.
4. **T4 — missing file**: invoke with a non-existent path. Expect immediate FAILURE with usage hint, no agents launched.
5. **T5 — iteration cap**: contrived case with a Reviewer that keeps raising new findings. Expect FAILURE at iter 10 with divergence signal.
