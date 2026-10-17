# R11: live comparison of implicit-add preprocessing

## Result

The controlled live comparison is complete. Keep `apply_implicit_add` for now. Turning it off did not improve the fixture's safety results, missed two additional intended actions across the repeated runs, asked one extra question, and cost about 1.6% more. This is a small diagnostic sample, not evidence that the heuristic is correct in general.

Both arms still produced additions on turns whose fixture expectation was to ask or make no change. The comparison therefore also confirms that prompt preprocessing alone does not resolve the refusal and pending-intent gaps. Those need server-side intent and mutation safeguards described in [the R11 design](REFACTORING_R11_DESIGN.md).

## Setup

- Provider and model: OpenRouter, `x-ai/grok-4.3` (the response identified the same model on all 44 calls in the latency run).
- Temperature: `0`; output limit: 256 tokens per call.
- Dataset: 12 synthetic dialogues from `backend/tests/fixtures/ai_dialogues/dialogues.json`, 22 turns per run. Fixture SHA-256: `1056a5d9f59e868e94a366a59654162743e3c95afa067f55f4b71f8e043a4c5b`.
- Arms: existing `apply_implicit_add` behavior versus an identity transform that leaves the input unchanged.
- Repetitions: two runs per arm, 22 requests per arm per run, 88 calls total. Runs used isolated pytest databases and synthetic accounts. They did not read or modify a real user's schedule.
- Spend cap: `$0.30` per complete run. The 22-call arm costs were about `$0.117` to `$0.119`, below the cap. Estimated pricing used `$1.25/M` input tokens and `$2.50/M` output tokens, matching the [OpenRouter model pricing page](https://openrouter.ai/x-ai/grok-4.3/pricing).
- Raw per-call prompts are represented by SHA-256 hashes. Raw responses and outcomes remain in local files under `/tmp/day-forge-r11/` and are not committed.

## Measurements

Counts below combine the two repetitions. Fixture intent uses `desired` where a known-gap case overrides the older `expect` result; otherwise it uses `expect`. A false add means the schedule changed on a turn whose desired result says `applied: false`. An excess ask means the fixture expects an apply but the live response asks a question. A missed apply means the fixture expects an apply but the planner did not apply it.

| Measure | Existing heuristic | Heuristic disabled |
| --- | ---: | ---: |
| Provider calls | 44 | 44 |
| False-add turns | 10 | 10 |
| Excess asks on intended applies | 10 | 11 |
| Missed intended applies | 10 | 12 |
| Estimated cost | `$0.2334` | `$0.2373` |
| Input / output tokens | 144,333 / 21,199 | 144,289 / 22,758 |

The repeated responses varied on 19 of 22 turns for the existing arm and 17 of 22 for the candidate. Prompt hashes matched between repetitions for only 16 of 22 existing-arm turns and 15 of 22 candidate turns. Temperature zero therefore did not make this routed provider/model setup reproducible, and some prompt context also changed between repeated requests.

Latency was captured only for the second run, so it is a rough operational sample rather than a comparison across both repetitions. Median and 95th-percentile latency were 6.5 s and 11.2 s for the existing arm, and 7.8 s and 15.5 s for the candidate.

## Interpretation and limits

The baseline was better on missed applies and excess asks, while both arms had the same number of false-add turns under the fixture's desired outcomes. In `replayed_prior_add`, the existing arm added the requested `Notes` block on both repetitions; with the heuristic disabled, one repetition asked instead of acting. This is evidence against deleting the heuristic based on this sample.

The live model also made incorrect additions on no-action or refusal turns in both arms. Because the sample is small and responses varied substantially, these counts should guide follow-up tests rather than be treated as a stable model-quality score. The test did not establish behavior across users, schedules, timezones, prompt versions, or future provider routing. It did not test durable recovery after a committed request loses its HTTP response.

Do not remove the replay or implicit-add protections on this evidence. Keep the existing deterministic fixture suite as the regression gate. Address refusal and unresolved follow-up state with the separate server-owned pending-intent design, and address lost-response retries with durable request identity before relying on natural-language replay behavior.
