"""Opt-in paid R11 runner; skipped during ordinary CI. See docs/R11_LIVE_COMPARISON.md."""

import datetime
import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from ai import service
from django.utils import timezone
from openai import AsyncOpenAI

from tests.r11_eval import (
    CASES,
    NOW,
    Budget,
    digest,
    prompt_stability,
    run_case,
    summarize,
)

LIVE = os.environ.get("R11_LIVE_AI") == "1"


@pytest.mark.skipif(not LIVE, reason="Paid provider comparison requires R11_LIVE_AI=1")
@pytest.mark.django_db
def test_live_r11_comparison(monkeypatch, settings):
    """Model quality failures belong in the report, not in ordinary unit CI."""
    output = Path(os.environ["R11_REPORT"])
    assert not output.exists(), "Choose a new R11_REPORT path to preserve earlier evidence"
    assert settings.LLM_API_KEY.strip(), "A real LLM_API_KEY must be configured"
    assert settings.LLM_BASE_URL.rstrip("/") == "https://openrouter.ai/api/v1"
    repeats = int(os.environ.get("R11_REPEATS", "2"))
    assert 1 <= repeats <= 5
    budget = Budget(float(os.environ.get("R11_BUDGET_USD", "1.00")))
    model = settings.LLM_MODEL
    # Retain the route/model metadata observed for this run. No secret is sent to this GET.
    metadata = httpx.get(
        f"https://openrouter.ai/api/v1/models/{model}/endpoints", timeout=30
    )
    metadata.raise_for_status()
    endpoints = metadata.json()["data"]
    # The reserve assumes these upper prices. Refuse a differently priced model/route.
    routes = [e for e in endpoints["endpoints"] if e["tag"] == "xai"]
    assert len(routes) == 1
    assert float(routes[0]["pricing"]["prompt"]) <= 0.00000125
    assert float(routes[0]["pricing"]["completion"]) <= 0.0000025
    cases = json.loads(CASES.read_text())
    assert len({case["id"] for case in cases}) == len(cases)
    report = {
        "methodology_version": 2,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "fixture_sha256": digest(cases), "frozen_now": NOW.isoformat(),
        "source_sha256": {
            name: digest(Path(__file__).with_name(name).read_text())
            for name in ("test_ai_live_comparison.py", "r11_eval.py")
        },
        "provider_metadata": endpoints, "model": model, "temperature": 0,
        "max_tokens": 1024, "timeout_seconds": 45, "sdk_max_retries": 0,
        "provider_routing": {
            "only": ["xai"], "allow_fallbacks": False,
            "max_price": {"prompt": 1.25, "completion": 2.5},
        },
        "repetitions": repeats, "budget_usd": budget.limit,
        "per_call_reserve_usd": budget.reserve_per_call,
        "planned_calls": len(cases) * repeats * 2,
        "rows": [], "complete": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report["spent_or_reserved_usd"] = budget.spent
        report["summary"] = summarize(report["rows"])
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(output)

    original = service.apply_implicit_add
    settings.LLM_REQUEST_TIMEOUT = report["timeout_seconds"]
    monkeypatch.setattr(timezone, "now", lambda: NOW)
    try:
        for repetition in range(1, repeats + 1):
            for index, case in enumerate(cases):
                arms = ["baseline", "implicit_add_off"]
                if (repetition + index) % 2 == 0:
                    arms.reverse()
                for arm in arms:
                    row = {"case": case["id"], "arm": arm, "repetition": repetition}
                    report["in_flight"] = row
                    monkeypatch.setattr(
                        service, "apply_implicit_add",
                        original if arm == "baseline" else lambda text, _messages: text,
                    )

                    async def complete(**kwargs):
                        kwargs["max_tokens"] = report["max_tokens"]
                        kwargs["extra_body"] = {"provider": report["provider_routing"]}
                        assert kwargs["temperature"] == 0 and kwargs["model"] == model
                        row["request"] = kwargs
                        row["request_sha256"] = digest(kwargs)
                        # A byte per token is a conservative bound for these text-only prompts.
                        reserve = (
                            len(json.dumps(kwargs["messages"], ensure_ascii=False).encode())
                            * 0.00000125 + report["max_tokens"] * 0.0000025
                        )
                        assert reserve <= budget.reserve_per_call
                        budget.reserve()
                        save()
                        started = time.perf_counter()
                        row["request_time_utc"] = datetime.datetime.now(datetime.UTC).isoformat()
                        try:
                            async with AsyncOpenAI(
                                api_key=settings.LLM_API_KEY,
                                base_url=settings.LLM_BASE_URL,
                                max_retries=0,
                            ) as client:
                                response = await client.chat.completions.create(**kwargs)
                        except Exception as error:
                            row["provider_error"] = type(error).__name__
                            # A lost response can still be billed. Reserve its cost and stop.
                            budget.spent += budget.reserve_per_call
                            raise
                        finally:
                            row["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
                        row["response_id"] = response.id
                        row["reported_model"] = response.model
                        row["reported_provider"] = getattr(response, "provider", None)
                        row["raw_response"] = response.choices[0].message.content
                        row["finish_reason"] = response.choices[0].finish_reason
                        row["usage"] = response.usage.model_dump() if response.usage else None
                        try:
                            budget.charge(row["usage"])
                        except RuntimeError:
                            row["accounting_error"] = True
                            raise
                        return response

                    monkeypatch.setattr(
                        service, "_get_client", lambda: SimpleNamespace(
                            chat=SimpleNamespace(completions=SimpleNamespace(create=complete))
                        ),
                    )
                    row.update(run_case(case))
                    report["rows"].append(row)
                    report.pop("in_flight", None)
                    save()
                    print(
                        f"R11 {len(report['rows'])}/{report['planned_calls']} "
                        f"{case['id']} {arm} run={repetition} "
                        f"passed={row['score']['passed']} billed=${budget.spent:.4f}", flush=True,
                    )
                    assert "provider_error" not in row, "Provider unavailable; see saved report"
                    assert "accounting_error" not in row, "Missing billed cost; see saved report"
                    assert row.get("usage") is not None, "Missing usage; see saved report"
                    assert budget.spent <= budget.limit, "Provider exceeded the spend cap"
        report["stable_request_hashes"] = prompt_stability(report["rows"])
        assert report["stable_request_hashes"], "Request drift invalidates the repeated comparison"
        report["complete"] = True
    finally:
        save()
    print(json.dumps(report["summary"], indent=2), flush=True)
