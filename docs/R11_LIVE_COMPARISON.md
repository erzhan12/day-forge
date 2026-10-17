# R11: corrected live comparison, version 2

## Result and correction of the earlier report

Keep `apply_implicit_add` on this evidence. The corrected sample passed 30/30 checks with the existing heuristic and 28/30 with the identity-transform candidate. Both misses concern a new `Notes` request after an earlier `Momentum` add. Neither arm made an unauthorized addition in the final reviewed sample. No production heuristic was removed.

The earlier report's false-add counts and quantitative quality comparison are withdrawn. Its script reused turns written for recorded model responses. A recorded question after `add Gym` was treated as mandatory even though the current contract permits an automatic add. It then sent `18:00` regardless of whether the live model had asked for a time. Different histories and schedules contaminated later comparisons. A changed schedule or an `applied` flag could not establish whether an action matched user intent.

Version 2 uses independent canonical states and scores actual schedule differences. This is an exploratory comparison with two repetitions per state, not a held-out benchmark or proof of general model safety.

## Method

The dataset is [live_cases.json](../backend/tests/fixtures/ai_dialogues/live_cases.json). Each case has an initial schedule, a complete synthetic transcript ending with a user request, and explicit authorized additions or updates. Prior assistant questions and accepted changes are canonical fixture inputs, not replies fabricated after a live response. Every case starts again for each arm and repetition. There are no scripted follow-up turns chained to an unpredictable live answer.

The 15 states cover English and Russian activities, automatic and timed adds, an answer to a pending time question, cancellation and refusal, an explicit repeat, a different title after a successful add, retry after a provider error, an unresolved sibling after partial application, category labels in both languages, uncertain-outcome retry, and a targeted category update. Partial-apply history includes the accepted block IDs. The uncertain-outcome case is a semantic snapshot, not an injected HTTP failure or a durability test.

Each request goes through the real SDK seam, chat view, validators, replay guard, category resolution, and planner in a disposable pytest database. An inner transaction rolls back each snapshot, including the fixture users and blocks. Both arms receive the same IDs, UTC clock, categories, rules, existing blocks, and prior transcript. The only candidate change is replacing `apply_implicit_add` with an identity transform.

The scorer matches new blocks one-to-one against authorized titles and checks constrained fields. An extra copy or an unrelated title counts as a false addition. Missing requested blocks count as missed actions. Wrong category, duration, or explicit time has its own counter. All existing blocks must survive unchanged except for named fields on the target of an authorized update. Non-200 responses cannot count as successful cancellations. A question is excessive only when the current intent supplies enough information to apply its mutation. The response's `applied` flag alone never establishes success.

Unrequested inferred categories and exact automatic placement times are not scored here. Automatic cases check activity, duration, and preservation of existing blocks; the domain suite separately covers automatic placement. Questions after cancellation do not count as excess mutation questions.

### Label review

Declared naming variants prevent cosmetic differences from becoming false safety findings. `Gym[2]` and `Gym [2]` both satisfy the duplicate-name rule. During review, the unquoted request `Reading emails 30 min` also exposed an overly strict title label: either `Reading emails` or `Reading emails 30 min` names the authorized activity. Both are accepted, while the 30-minute duration remains mandatory.

The latter label was corrected after capture. No provider-bound input changed, and no final-series response was excluded. The evidence retains `capture_expected`, `capture_score`, `capture_fixture_sha256`, and a `label_review` entry alongside the reviewed expectations. This correction removes one naming-related false-add/missed-action pair from the candidate's original capture score. The `Notes` failures remain failures. The review is a limitation of this exploratory sample, and its results must not be presented as a pre-registered quality estimate.

The final fixture's canonical JSON SHA-256 is `f37855cdf092a6174ca781b1ac293562e0755d6400718df0797d59a912856f0f`. This is the hash produced by `tests.r11_eval.digest`, not a hash of the JSON file's whitespace.

## Provider configuration and controls

| Setting | Value |
| --- | --- |
| Model requested and reported | `x-ai/grok-4.3` |
| Reported provider | `xAI` on all 60 responses |
| Routing | `only: [xai]`, fallbacks disabled |
| Price ceiling | $1.25/M prompt tokens, $2.50/M completion tokens |
| Temperature | 0 |
| Requested `max_tokens` | 1024 |
| Timeout / SDK retries | 45 seconds / 0 |
| Fixture clock / timezone | 2026-04-18 08:00 / UTC |
| Schedule window | 06:00–23:00 |
| Repetitions | 2 per arm and state |
| Order | Paired calls, with first arm alternating by case and repetition |
| Local spend guard | $0.80, with a $0.03 pre-request reserve |

The runner saves the public endpoint metadata observed at execution. It checks the selected route's prices and refuses a more expensive route. Provider and price restrictions use OpenRouter's [routing controls](https://openrouter.ai/blog/insights/model-routing/). The alias and returned metadata do not guarantee immutable model weights across future runs.

All 30 case/arm groups had identical complete request hashes between repetitions. Paired arms had identical context and prior transcript. Only three states changed the provider-bound latest text: `fresh_bare_en`, `fresh_bare_ru`, and `new_title_after_success`. The other 12 states are unchanged-input controls. Zero temperature does not guarantee identical model responses.

## Results

The final series completed all 60 calls without provider errors, missing usage, or invalid responses. Cost below is the returned OpenRouter `usage.cost`, including cache effects, rather than a token-price estimate. OpenRouter documents this field as the [amount charged to the account](https://openrouter.ai/docs/cookbook/administration/usage-accounting).

| Measurement, both repetitions combined | Existing heuristic | Heuristic disabled |
| --- | ---: | ---: |
| Calls | 30 | 30 |
| State checks meeting the reviewed expectation | 30 | 28 |
| False additions | 0 | 0 |
| Missed authorized actions | 0 | 2 |
| Wrong constrained fields | 0 | 0 |
| Unauthorized changes to existing blocks | 0 | 0 |
| Excess questions | 0 | 1 |
| Invalid responses | 0 | 0 |
| Billed cost | $0.0558636 | $0.0741210 |
| Input / output tokens | 98,648 / 10,976 | 98,638 / 11,779 |
| Median latency | 4.19 s | 4.47 s |
| P95 latency, nearest rank | 6.74 s | 12.76 s |

Total billed cost for the final series: **$0.1299846**. Billing and latency vary with cache state and provider execution. Their differences are observations from this run, not stable cost or speed advantages attributable to the heuristic.

Latency includes creation and closure of a fresh SDK client. This is not a production ASGI connection-pool benchmark.

A calibration series was stopped after 30 completed calls while the scorer's suffix-spacing labels were being corrected. Its returned usage accounted for $0.05907545, with one subsequent in-flight call lacking returned usage after interruption. It is excluded from the table and the 60-call evidence. The earlier version-1 series is also excluded.

| State | Existing heuristic | Heuristic disabled |
| --- | ---: | ---: |
| `fresh_bare_en` | 2/2 | 2/2 |
| `fresh_bare_ru` | 2/2 | 2/2 |
| `fresh_automatic_add` | 2/2 | 2/2 |
| `explicit_add` | 2/2 | 2/2 |
| `canonical_time_answer` | 2/2 | 2/2 |
| `cancel_pending` | 2/2 | 2/2 |
| `refuse_pending` | 2/2 | 2/2 |
| `explicit_repeat` | 2/2 | 2/2 |
| `new_title_after_success` | 2/2 | 0/2 |
| `retry_after_provider_error` | 2/2 | 2/2 |
| `canonical_partial_followup` | 2/2 | 2/2 |
| `category_label_ru` | 2/2 | 2/2 |
| `category_label_en` | 2/2 | 2/2 |
| `uncertain_outcome_retry` | 2/2 | 2/2 |
| `targeted_category_update` | 2/2 | 2/2 |

In the first candidate `Notes` response, the model proposed another `Momentum` instead. The replay guard blocked that action and returned a clarifying question. In the second repetition, the model returned no actions and explained that there was no new request. Neither repetition added `Notes`. The existing arm added `Notes` on both repetitions. These are missed requests, not false additions, and they provide a concrete reason to retain the heuristic while further evaluation continues.

## Reproduction and evidence

The paid runner is [test_ai_live_comparison.py](../backend/tests/test_ai_live_comparison.py); state setup, scoring, budgeting, and summaries are in [r11_eval.py](../backend/tests/r11_eval.py). With a working OpenRouter key configured in `.env`, run from the repository root, choosing an output path that does not exist:

```sh
LLM_MODEL=x-ai/grok-4.3 \
LLM_BASE_URL=https://openrouter.ai/api/v1 \
R11_LIVE_AI=1 \
R11_REPORT=/tmp/r11-new-report.json \
R11_BUDGET_USD=0.80 \
R11_REPEATS=2 \
uv run pytest backend/tests/test_ai_live_comparison.py -q -s
```

The runner is skipped without `R11_LIVE_AI=1`. A passing paid test means capture completed with stable requests, not that all model outputs passed their semantic checks. Failures of those checks are measurements in the report. A provider error, missing billed cost, budget stop, or request drift leaves the experiment incomplete. Reports are saved after every case, with the current in-flight request retained during a call. Automatic SDK retries are disabled; unknown usage reserves a call's cost and stops further calls.

The final reviewed [compressed evidence](evaluations/r11-live-v2-2026-10-17.json.gz) contains the complete synthetic provider requests and raw responses, request hashes, runtime source hashes, model/provider identifiers, usage, latency, canonical inputs, parsed actions, planner payloads, before/after blocks, and scores. It contains no user data or credentials. Extract it with:

```sh
gzip -dc docs/evaluations/r11-live-v2-2026-10-17.json.gz > /tmp/r11-reviewed.json
```

The untouched capture and reviewed JSON also remain locally at `/tmp/day-forge-r11/corrected-final-20261017.json` and `/tmp/day-forge-r11/reviewed-final-20261017.json`. The evidence distinguishes the capture fixture hash from the reviewed gold hash. Source hashes refer to canonical JSON-encoded source text at capture time.

[Test coverage](../backend/tests/test_r11_eval.py) checks the scorer's failure boundaries, snapshot rollback and stable inputs, and replay of all 60 captured live responses through the real SDK seam, view, and planner without network access. The original [recorded dialogue corpus](../backend/tests/test_ai_dialogue_corpus.py) remains a separate deterministic server regression suite.

Validation after the correction: 2,033 backend tests passed with the paid runner skipped in the ordinary suite; its explicit live run passed separately. All 1,387 frontend tests, Ruff, Vue type-check, and production build passed. The 25 evaluation tests include the replay of the saved 60-call capture.

To verify the evaluation and replay the saved responses without provider calls:

```sh
uv run pytest backend/tests/test_r11_eval.py -q
```

## Limits and next decision

This experiment tests single-turn outcomes conditional on coherent supplied history. It does not show that a live conversation will naturally reach every canonical state, verify browser transcript wiring, inject an actual lost response after commit, or establish durable idempotency. Those require different tests. Passing refusal examples here does not close the known server-side gap for an adversarial or incorrect model action after cancellation.

No branch should be removed on a two-repetition diagnostic sample. The repeated `Notes` miss supports retaining the current preprocessing. Any proposed removal should first address that case, then run an unchanged or independently reviewed intent corpus again. Server-owned pending intent and durable request identity remain separate designs in [the R11 plan](REFACTORING_R11_DESIGN.md).
