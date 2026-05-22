# Plan-Debate Skill — Design

**Date:** 2026-05-22
**Author:** Claude (brainstorming session with @erzhan12)
**Status:** Spec — awaiting implementation plan

## 1. Purpose

A Claude Code skill that produces a high-quality feature plan by running an
**adversarial collaboration loop** between two independent sub-agents:

- **Planner (Agent1)** — drafts and revises a `docs/features/NNNN_PLAN.md`
  following the canonical `commands/plan_feature.md` format.
- **Reviewer (Agent2)** — performs a thorough independent review of the plan
  and emits structured findings.

The orchestrator (the main Claude conversation that invoked the skill) shuttles
findings and rebuttals between the two agents in memory until the Reviewer
returns zero open findings, or a hard cap of **10 iterations** is hit.

The design's central constraint is **independence to reduce bias**: each
sub-agent runs in an isolated `Agent`-tool context and never sees the other
agent's reasoning verbatim — only structured summaries shuttled by the
orchestrator.

## 2. Triggering & Inputs

**Trigger:** the skill is invoked via the `Skill` tool or the
`/plan-debate` slash command.

**Inputs:**

1. `<feature description>` — required free-text description of the feature.
2. `[spec_path]` — optional path to an existing spec/PRD. If provided,
   Planner ingests its content as additional context for the first plan
   draft.

**Output:**

- `docs/features/NNNN_PLAN.md` — single canonical artifact (next available
  feature number, starting at `0001`).
- Final orchestrator message to the user: either
  - `SUCCESS` with path to the plan and iteration count, or
  - `FAILURE` with the path to the (partial) plan, the list of unresolved
    findings, the latest rebuttals, and a prompt for the user to choose
    one of: accept-as-is / continue manually / abandon.

## 3. File Layout

```
~/.claude/skills/plan-debate/
  SKILL.md       # Orchestrator instructions (this is what the Skill tool loads)
  planner.md     # System prompt body for Agent1 (Planner)
  reviewer.md    # System prompt body for Agent2 (Reviewer), incl. JSON schema
```

The skill ships with a **canonical fallback** copy of the plan-format spec
embedded in `planner.md` under the heading `## Plan format spec (canonical)`.
At runtime, the orchestrator checks whether the **current project** contains a
`commands/plan_feature.md`; if it does, that file's content overrides the
fallback (per-project override). This keeps the skill portable while honoring
project-specific plan conventions like day-forge's.

## 4. Orchestrator Flow

The orchestrator runs in the main conversation. It owns the loop, the
iteration counter, and the in-memory finding/response state.

```
1. Parse inputs: feature_description, optional spec_path.
   Resolve plan_format_spec:
     - if ./commands/plan_feature.md exists → use its content
     - else → use canonical fallback from planner.md

2. Determine next feature number N:
     - scan docs/features/ for existing NNNN_PLAN.md, take max + 1

3. Initial planning round (iter = 0):
   a. Launch Agent(Planner) with:
        - feature_description
        - spec content (if spec_path provided)
        - plan_format_spec
        - target path: docs/features/<NNNN>_PLAN.md
        - instruction: "You may ask up to 5 clarifying questions before
          writing the plan. If you have questions, return them as JSON
          {questions: [...]} and do nothing else."
   b. If Planner returned questions:
        - orchestrator surfaces them to the user, awaits answers
        - relaunches Agent(Planner) with original prompt + answers
        - (no nested clarification rounds — single Q&A pass)
   c. Planner writes PLAN.md and returns {plan_path, summary}.

4. iter = 1
5. open_findings = {}   # id -> finding record
   prior_responses = []  # author responses from previous iter (passed to Reviewer)

6. Loop while iter <= 10:
     a. Launch Agent(Reviewer) with:
          - path to PLAN.md (Reviewer Reads it itself — see §11)
          - α-history: list of prior findings this Reviewer raised + author
            responses to each (structured summary, NOT prior Reviewer's
            free-text reasoning)
        Reviewer returns:
          {
            "verdict": "approve" | "changes_requested",
            "new_findings": [...],
            "prior_findings_status": [{id, status, note}]
          }

     b. Reconcile open_findings:
          - for each entry in prior_findings_status:
              if status in ("closed_by_fix", "closed_by_rationale"):
                  remove from open_findings
              else (still_open): keep
          - finding IDs NOT mentioned in prior_findings_status default to
            still_open (failsafe)
          - add all new_findings to open_findings

     c. If open_findings == {} → SUCCESS, exit loop

     d. Launch Agent(Planner) with:
          - path to PLAN.md (Planner Reads it itself before editing)
          - open_findings list
          - α-history: list of this Planner's prior rebuttals (structured,
            id + one-line rationale, NOT free-text reasoning)
        Planner returns:
          {
            "responses": [{id, action: "fixed" | "rebutted", note}]
          }
        Planner is expected to use Edit to modify PLAN.md for "fixed"
        actions.

     e. Diff guard:
          - run `git diff docs/features/<NNNN>_PLAN.md`
          - for each response with action="fixed": if no changes touch the
            corresponding section/heading, force status to "still_open" in
            the next Reviewer round (record as "claimed_fixed_no_diff")

     f. Store responses → prior_responses for next iteration's Reviewer.
     g. iter += 1

7. If iter > 10 and open_findings != {}:
     FAILURE: emit summary to user containing
       - path to PLAN.md
       - list of unresolved findings (id, severity, issue, last status)
       - latest Planner responses (rebuttal text where action=rebutted)
       - prompt: "Accept plan as-is, continue manually, or abandon?"
```

## 5. Sub-Agent Prompts (Shape)

### Planner (Agent1)

System-prompt body (`planner.md`):

- Role: "You are a senior engineer drafting a technical implementation plan."
- Plan format spec: embedded canonical, overridden by project file when
  available.
- Two operating modes determined by orchestrator prompt:
  - **Initial mode (iter=0):** write the plan from scratch, or ask up to 5
    clarifying questions first.
  - **Revision mode (iter≥1):** read open findings, for each one either
    `Edit` PLAN.md to address it (action=fixed) or return a rebuttal
    (action=rebutted) with rationale.
- Strict output: a single ```json fenced block matching the schema in §6.
- No conversational text outside the JSON in revision mode. In initial
  mode, return either questions JSON or write the file and return
  `{plan_path, summary}` JSON.

### Reviewer (Agent2)

System-prompt body (`reviewer.md`):

- Role: "You are an independent senior engineer reviewing a technical
  implementation plan for correctness, completeness, and rigor."
- Review rubric (the agent applies this from scratch each iteration):
  - Correctness of technical approach
  - Completeness of phases and data-layer coverage
  - Missing files/functions in the impact analysis
  - Algorithmic gaps or under-specified steps
  - Naming, ID conventions, and consistency with referenced project rules
  - Risk / blast-radius analysis
- Explicit anti-anchoring instruction: "Re-read PLAN.md as if for the first
  time. The list of your prior findings (with author responses) is
  provided so you do not re-discover already-handled issues — not so you
  can defend earlier positions. If the author's fix or rationale is
  convincing, mark the finding `closed_by_fix` or `closed_by_rationale`."
- Strict output: one ```json fenced block matching the schema in §6.

## 6. JSON Schemas

### Reviewer output

```json
{
  "verdict": "approve | changes_requested",
  "new_findings": [
    {
      "id": "F-<iter>-<n>",
      "severity": "critical | major | minor",
      "location": "<section heading or line range in PLAN.md>",
      "issue": "<one-paragraph description of the issue>",
      "suggested_fix": "<optional concrete suggestion>"
    }
  ],
  "prior_findings_status": [
    {
      "id": "F-1-2",
      "status": "closed_by_fix | closed_by_rationale | still_open",
      "note": "<why>"
    }
  ]
}
```

### Planner output (revision mode)

```json
{
  "responses": [
    {
      "id": "F-2-1",
      "action": "fixed",
      "note": "<short diff summary>"
    },
    {
      "id": "F-2-2",
      "action": "rebutted",
      "note": "<rationale>"
    }
  ]
}
```

### Planner output (initial mode, with questions)

```json
{
  "questions": [
    "<question 1>",
    "<question 2>"
  ]
}
```

### Planner output (initial mode, plan written)

```json
{
  "plan_path": "docs/features/0042_PLAN.md",
  "summary": "<one-paragraph summary of the plan>"
}
```

## 7. Open / Closed Logic

The orchestrator maintains a single map `open_findings: id -> record`.

On each Reviewer response:

1. For each `(id, status)` in `prior_findings_status`:
   - `closed_by_fix` or `closed_by_rationale` → remove `id` from
     `open_findings`.
   - `still_open` → keep.
2. For each id currently in `open_findings` but **not** present in
   `prior_findings_status` → treat as `still_open` (failsafe; protects
   against a Reviewer silently dropping a finding).
3. Add every entry in `new_findings` to `open_findings` (collision on `id`
   is impossible by construction: id = `F-<iter>-<n>` where `iter` is
   monotonically increasing).

**Convergence:** `len(open_findings) == 0` → SUCCESS.

**Diff guard override:** after Planner returns, for any response with
`action="fixed"` whose claimed change is not visible in
`git diff PLAN.md`, the orchestrator records `claimed_fixed_no_diff = true`
on the corresponding finding. That finding will be force-set to
`still_open` on the next iteration regardless of Reviewer's call.

## 8. α-History Format (Memory Passed to Each Agent)

The α-history compromise is the load-bearing design choice for "no bias."
Each agent receives a **structured summary** of its own prior involvement,
never its prior free-text reasoning.

**To Reviewer at iter N (for N ≥ 1):**

```
PRIOR FINDINGS YOU RAISED:
  F-1-1 [major] "Phase 2 missing migration step" — author response: fixed (added
    migration to §Data layer)
  F-1-2 [minor] "Naming inconsistency on FooBar" — author response: rebutted
    ("intentional, follows project convention X")
  F-2-1 [critical] "API contract breaks existing clients" — author response: fixed

Re-read PLAN.md fresh. Tell me which of the above are now closed (by fix
or by rationale) and what NEW findings you have.
```

**To Planner at iter N (for N ≥ 1):**

```
OPEN FINDINGS TO ADDRESS:
  F-N-1 [major] "..." (location: "...")
  ...

YOUR PRIOR REBUTTALS (carried forward, do not repeat verbatim):
  F-1-2: "intentional, follows project convention X"

For each open finding, either edit PLAN.md and return action=fixed, or
return action=rebutted with rationale.
```

## 9. Edge Cases

| Case | Behavior |
|---|---|
| Planner asks clarifying questions (iter=0, ≤5) | Orchestrator surfaces to user, awaits answers, relaunches Planner once. Single Q&A pass. |
| Reviewer returns `verdict=approve` with `new_findings=[]` on iter=1 | Immediate SUCCESS (the "first plan is perfect" path). |
| Malformed JSON in any agent response | One automatic retry of that agent with prompt "Output was malformed, return only the JSON block." Second failure → FAILURE with raw response shown. |
| Planner action=fixed but PLAN.md diff is empty for relevant section | Diff guard kicks in: finding force-set to `still_open` next iter. |
| Reviewer omits a prior finding from `prior_findings_status` | Failsafe: treated as `still_open`. |
| iter = 10 and `open_findings != {}` | FAILURE with user arbitration prompt (see §2 output). |
| Same finding ping-pongs (Planner rebuts, Reviewer keeps re-opening) for 3+ iterations | Not blocked. Logged as `divergence_signal` in the final summary so the user can see persistent disagreements at the end. |
| Spec file path provided but unreadable | Surface error to user before launching Planner. |
| `docs/features/` does not exist | Orchestrator creates it. |

## 10. Non-Goals (YAGNI)

- **No `REVIEW.md` artifact.** All review state is in-memory.
- **No structured diff parsing.** `git diff PLAN.md` non-empty/empty is the
  only signal used.
- **No third arbitrator agent.** 10 iterations + user arbitration is the
  ceiling.
- **No persistence between skill invocations.** Each skill run is
  standalone.
- **No different models per agent.** Both agents are Opus; independence
  comes from isolated `Agent`-tool contexts and the α-history discipline.
- **No automatic plan-number conflict resolution.** If a parallel
  invocation grabbed `NNNN` between scan and write, Planner's write
  collision surfaces as an error and the user re-invokes.

## 11. Sub-Agent Invocation Detail

Both agents are launched via:

```python
Agent(
    description="<short label>",
    subagent_type="general-purpose",
    model="opus",
    prompt="<full instructions + α-history + current state>",
)
```

`general-purpose` is chosen because both agents need full tool access:
Planner uses `Read` + `Edit` (or `Write` for the initial draft) on
PLAN.md; Reviewer uses `Read` on PLAN.md. The orchestrator passes the
**path** to PLAN.md in the prompt; each agent reads the file itself,
ensuring the Reviewer always sees the version on disk at the moment of
review (no stale-content races if the Planner's Edit landed
mid-orchestration). `Plan` subagent type is read-only and unsuitable for
Planner.

The `model` parameter is set explicitly to `"opus"` so that the inheritance
behavior (sub-agent inherits parent's model) does not silently downgrade if
the parent conversation happens to be running on a smaller model.

## 12. Skill Files — Drafting Notes

### SKILL.md (orchestrator)

- Frontmatter: `name: plan-debate`, `description:` triggers on "plan a
  feature", "iterate on plan", "review a feature plan with two agents",
  etc. (Final wording to be tuned during implementation.)
- Body: the orchestrator algorithm from §4 rendered as a runnable
  procedure with explicit pseudo-code for the loop, plus the schemas from
  §6 inline so the orchestrator can validate agent output.

### planner.md

- Role block.
- Plan-format-spec block (canonical fallback; orchestrator will swap in
  project file when present).
- Initial-mode instructions (write file or ask ≤5 questions).
- Revision-mode instructions (open-findings handling).
- Output schemas (initial-questions / initial-written / revision).

### reviewer.md

- Role block.
- Review rubric (concrete categories).
- Anti-anchoring paragraph.
- α-history-reading instructions.
- Output schema with examples for `closed_by_fix` /
  `closed_by_rationale` / `still_open`.

## 13. Manual Test Plan (for the implementation phase)

Once the skill is implemented, manual verification:

1. **Happy path (iter=1 success):** invoke on a trivially simple feature
   ("add a `--version` flag to CLI"). Expect Reviewer to approve in iter
   1.
2. **Iterative convergence:** invoke on a medium feature ("add basic
   pagination to schedules list endpoint"). Expect 2-4 iterations,
   convergence to zero findings.
3. **Rebuttal acceptance:** craft a feature where Reviewer is likely to
   raise a stylistic concern Planner can reasonably push back on (e.g.
   naming). Verify `closed_by_rationale` path works end-to-end.
4. **Hard cap:** synthetic test where Reviewer prompt is amplified to
   nitpick aggressively. Verify FAILURE path at iter 10 surfaces
   unresolved findings cleanly.
5. **Clarifying questions:** invoke with deliberately ambiguous feature
   description. Verify Planner asks questions, orchestrator forwards, Q&A
   completes, plan gets written.
6. **Project override:** verify that running in day-forge picks up
   `commands/plan_feature.md` as the plan-format spec, while running in a
   project without that file uses the canonical fallback.

## 14. Out of Scope (for this spec)

- Full text of `planner.md` and `reviewer.md` system prompts — drafted
  during implementation.
- Final wording of `SKILL.md` frontmatter `description` for trigger
  discoverability — tuned during implementation.
- Telemetry / observability beyond the final summary returned to the user.
