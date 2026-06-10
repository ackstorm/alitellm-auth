# SPDX-License-Identifier: Apache-2.0
"""Pure-unit tests for app/stats.py aggregation (no HTTP / no respx).

Asserts against the verbatim v1.85.1 fixtures captured in Plan 01. The captured
daily-activity fixtures are single-day windows; to prove the per-model/per-key
"sum across days" fold, the multi-day cases build a synthetic two-day input by
reusing the real single-day result block (same v1.85.1 shape, twice).
"""

import copy
import json
from pathlib import Path

import pytest

import hashlib

from app.stats import (
    aggregate_window,
    build_stats_contract,
    compute_deltas,
    resolve_key_display,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# aggregate_window
# ---------------------------------------------------------------------------


def test_aggregate_window_totals_from_metadata():
    data = _load("daily_activity_current.json")
    agg = aggregate_window(data)

    assert agg["requests"] == 11
    assert agg["tokens"] == 10018
    assert agg["spend"] == 0.023427


def test_aggregate_window_series_one_entry_per_day():
    data = _load("daily_activity_current.json")
    agg = aggregate_window(data)

    assert len(agg["series"]) == len(data["results"])
    entry = agg["series"][0]
    assert entry["date"] == "2026-04-01"
    assert entry["spend"] == 0.023427
    assert entry["requests"] == 11


def test_aggregate_window_series_includes_tokens():
    data = _load("daily_activity_current.json")
    agg = aggregate_window(data)
    day0 = data["results"][0]
    assert agg["series"][0]["tokens"] == int(day0["metrics"]["total_tokens"])


def test_aggregate_window_failed_requests_total_and_per_day():
    data = _load("daily_activity_current.json")
    agg = aggregate_window(data)
    assert agg["failed_requests"] == int(
        data["metadata"]["total_failed_requests"]
    )
    day0 = data["results"][0]
    assert agg["series"][0]["failed"] == int(day0["metrics"]["failed_requests"])


def test_build_stats_contract_totals_include_failed_requests():
    cur = aggregate_window(_load("daily_activity_current.json"))
    contract = build_stats_contract(
        cur, cur, {"current": 0, "max_budget": None}, {}, dict(_CAPABILITIES), _RANGE
    )
    assert contract["totals"]["failed_requests"] == cur["failed_requests"]


def test_aggregate_window_models_summed_across_days():
    """A model appearing on 2 days has its metrics ADDED (the core fold)."""
    data = _load("daily_activity_current.json")
    two_day = {
        "results": [data["results"][0], copy.deepcopy(data["results"][0])],
        "metadata": data["metadata"],
    }
    two_day["results"][1]["date"] = "2026-04-02"

    agg = aggregate_window(two_day)
    models = {m["model"]: m for m in agg["models"]}

    # flash-lite was 1 request / 68 tokens / spend 8e-06 on one day → doubled.
    lite = models["gemini/gemini-flash-lite-latest"]
    assert lite["requests"] == 2
    assert lite["total_tokens"] == 136
    assert lite["input_tokens"] == 128  # prompt_tokens 64 * 2
    assert lite["output_tokens"] == 8  # completion_tokens 4 * 2
    assert lite["spend"] == 8e-06 * 2

    # series reflects both days.
    assert len(agg["series"]) == 2


def test_aggregate_window_keys_summed_and_present():
    data = _load("daily_activity_current.json")
    agg = aggregate_window(data)

    keys = {k["id"]: k for k in agg["keys"]}
    h = "195b8b1f2c4e46945209387ec13e08ea7d74714fd088cd118b928630a03f2317"
    assert h in keys
    assert keys[h]["requests"] == 11
    assert keys[h]["spend"] == 0.023427


def test_aggregate_window_real_zero_tokens_kept():
    """prompt/completion 0 that are real zeros stay 0 (D-08), not None."""
    data = _load("daily_activity_prior.json")
    agg = aggregate_window(data)

    models = {m["model"]: m for m in agg["models"]}
    veo = models["veo-3.1-generate-preview"]
    assert veo["input_tokens"] == 0
    assert veo["output_tokens"] == 0
    assert veo["spend"] == 3.2


def test_aggregate_window_failed_requests_diverge_from_model_breakdown():
    """WR-04: headline totals (metadata) intentionally diverge from summed models.

    The prior fixture has 4 total requests (1 success + 3 failed). The single
    success is attributed to veo-3.1-generate-preview; the 3 failed requests have
    no `models` entry but DO appear under `api_keys`. So sum(models[].requests)
    under-reports the headline while sum(keys[].requests) tracks it. This is by
    design (totals = metadata source of truth); the test pins it so the divergence
    is never mistaken for a regression.
    """
    data = _load("daily_activity_prior.json")
    agg = aggregate_window(data)

    assert agg["requests"] == 4  # metadata.total_api_requests (incl. failed)
    # Per-model breakdown omits the 3 model-less failed requests → diverges low.
    assert sum(m["requests"] for m in agg["models"]) == 1
    # Per-key breakdown captures the failed requests → reconciles with the total.
    assert sum(k["requests"] for k in agg["keys"]) == 4


def test_aggregate_window_empty_is_real_zero_not_null():
    data = _load("daily_activity_empty.json")
    agg = aggregate_window(data)

    assert agg["requests"] == 0
    assert agg["tokens"] == 0
    assert agg["spend"] == 0
    assert agg["series"] == []
    assert agg["models"] == []
    assert agg["keys"] == []


# ---------------------------------------------------------------------------
# compute_deltas
# ---------------------------------------------------------------------------


def test_compute_deltas_nonzero_prior():
    cur = {"requests": 110, "tokens": 2000, "spend": 12.0}
    prev = {"requests": 100, "tokens": 1000, "spend": 10.0}
    deltas = compute_deltas(cur, prev)

    assert deltas["requests_pct"] == 0.1  # (110-100)/100
    assert deltas["tokens_pct"] == 1.0  # (2000-1000)/1000
    assert deltas["spend_pct"] == 0.2  # (12-10)/10


def test_compute_deltas_zero_prior_is_null():
    """Div-by-zero guard: a 0 prior yields None, not a crash and not +inf."""
    cur = {"requests": 10, "tokens": 5, "spend": 1.0}
    prev = {"requests": 0, "tokens": 0, "spend": 0.0}
    deltas = compute_deltas(cur, prev)

    assert deltas["requests_pct"] is None
    assert deltas["tokens_pct"] is None
    assert deltas["spend_pct"] is None
    assert deltas["avg_cost_per_1m_tokens_pct"] is None


# ---------------------------------------------------------------------------
# build_stats_contract
# ---------------------------------------------------------------------------

_CAPABILITIES = {
    "token_split": True,
    "per_model_last_used": True,
    "per_key_spend": True,
    "deltas": True,
}

_RANGE = {
    "start": "2026-04-01",
    "end": "2026-04-30",
    "days": 30,
    "compare": {"start": "2026-03-02", "end": "2026-03-31"},
}


def test_build_stats_contract_shape_and_capabilities():
    cur = aggregate_window(_load("daily_activity_current.json"))
    prev = aggregate_window(_load("daily_activity_prior.json"))
    budget = {"current": 0.0, "max_budget": 500.0, "source": "user"}

    contract = build_stats_contract(cur, prev, budget, {}, dict(_CAPABILITIES), _RANGE)

    assert set(contract.keys()) == {
        "range",
        "totals",
        "series",
        "models",
        "keys",
        "budget",
        "capabilities",
    }
    assert contract["capabilities"]["per_key_spend"] is True
    assert contract["range"]["days"] == 30
    # avg_cost_per_1m_tokens = spend / tokens * 1_000_000, guarded.
    assert contract["totals"]["avg_cost_per_1m_tokens"] is not None
    assert "deltas" in contract["totals"]


def test_build_stats_contract_zero_fills_missing_days():
    cur = aggregate_window(_load("daily_activity_current.json"))  # day: 2026-04-01
    rng = {
        "start": "2026-03-31",
        "end": "2026-04-02",
        "days": 3,
        "compare": {"start": "2026-03-28", "end": "2026-03-30"},
    }
    contract = build_stats_contract(
        cur, cur, {"current": 0, "max_budget": None}, {}, dict(_CAPABILITIES), rng
    )
    series = contract["series"]
    assert [str(p["date"])[:10] for p in series] == [
        "2026-03-31",
        "2026-04-01",
        "2026-04-02",
    ]
    # Filled days are REAL zeros (D-08: in-window absence of usage IS zero usage).
    assert series[0]["spend"] == 0.0
    assert series[0]["requests"] == 0
    assert series[0]["tokens"] == 0
    # The real day keeps its figures.
    assert series[1]["requests"] > 0


def test_build_stats_contract_keys_ranked_by_spend_desc():
    data = _load("daily_activity_prior.json")
    cur = aggregate_window(data)
    contract = build_stats_contract(
        cur, cur, {"current": 0, "max_budget": None}, {}, dict(_CAPABILITIES), _RANGE
    )

    spends = [k["spend"] for k in contract["keys"]]
    assert spends == sorted(spends, reverse=True)


def test_build_stats_contract_models_spend_pct_guarded():
    cur = aggregate_window(_load("daily_activity_current.json"))
    contract = build_stats_contract(
        cur, cur, {"current": 0, "max_budget": None}, {}, dict(_CAPABILITIES), _RANGE
    )

    total = sum(m["spend"] for m in contract["models"])
    for m in contract["models"]:
        if total:
            assert abs(m["spend_pct"] - m["spend"] / total) < 1e-9
        else:
            assert m["spend_pct"] is None


def test_build_stats_contract_last_used_null_flips_capability():
    """No last_used map → models[].last_used == null + capability false."""
    cur = aggregate_window(_load("daily_activity_current.json"))
    caps = dict(_CAPABILITIES)
    contract = build_stats_contract(cur, cur, {"current": 0, "max_budget": None}, {}, caps, _RANGE)

    assert contract["capabilities"]["per_model_last_used"] is False
    for m in contract["models"]:
        assert m["last_used"] is None


def test_build_stats_contract_last_used_present_keeps_capability():
    cur = aggregate_window(_load("daily_activity_current.json"))
    last_used = {"gemini/gemini-flash-latest": "2026-04-01T09:49:44.420000Z"}
    contract = build_stats_contract(
        cur, cur, {"current": 0, "max_budget": None}, last_used, dict(_CAPABILITIES), _RANGE
    )

    assert contract["capabilities"]["per_model_last_used"] is True
    by_model = {m["model"]: m for m in contract["models"]}
    assert by_model["gemini/gemini-flash-latest"]["last_used"] == "2026-04-01T09:49:44.420000Z"
    # A model without a last_used entry stays null.
    assert by_model["gemini/gemini-3-pro-preview"]["last_used"] is None


def test_build_stats_contract_budget_with_max():
    cur = aggregate_window(_load("daily_activity_empty.json"))
    budget = {
        "current": 4.2,
        "max_budget": 10.0,
        "budget_duration": "30d",
        "source": "user",
    }
    contract = build_stats_contract(cur, cur, budget, {}, dict(_CAPABILITIES), _RANGE)

    b = contract["budget"]
    assert b["has_budget"] is True
    assert b["pct"] == pytest.approx(0.42)
    assert b["max_budget"] == 10.0
    # The budget PERIOD passes through so the UI can disambiguate "$X of $Y".
    assert b["budget_duration"] == "30d"


def test_build_stats_contract_null_budget_pct_none():
    """null max_budget → pct None + has_budget False (D-08)."""
    cur = aggregate_window(_load("daily_activity_empty.json"))
    budget = {"current": 0.0, "max_budget": None, "source": "unknown"}
    contract = build_stats_contract(cur, cur, budget, {}, dict(_CAPABILITIES), _RANGE)

    b = contract["budget"]
    assert b["has_budget"] is False
    assert b["pct"] is None


def test_build_stats_contract_empty_totals_are_zero_not_null():
    cur = aggregate_window(_load("daily_activity_empty.json"))
    contract = build_stats_contract(
        cur, cur, {"current": 0, "max_budget": None}, {}, dict(_CAPABILITIES), _RANGE
    )

    t = contract["totals"]
    assert t["requests"] == 0
    assert t["tokens"] == 0
    assert t["spend"] == 0
    # avg_cost guarded for 0 tokens → None (unavailable, not 0).
    assert t["avg_cost_per_1m_tokens"] is None


# ---------------------------------------------------------------------------
# resolve_key_display — opaque lk- alias → friendly name join (TOP API KEYS fix)
# ---------------------------------------------------------------------------


def _alias_id(opaque: str) -> str:
    """The key-list id for an opaque alias == sha256(alias) (litellm _get_key_id)."""
    return hashlib.sha256(opaque.encode()).hexdigest()


def test_resolve_key_display_joins_opaque_alias_to_friendly_name():
    """The spend row's opaque lk- alias → friendly name, id → stable key-list id."""
    opaque = "lk-80cffcc549141094"
    kid = _alias_id(opaque)
    # Spend-log row: opaque alias + a spend-log key hash (NOT the key-list id).
    stats_keys = [{"id": "spendhash_abc", "key_alias": opaque, "requests": 25, "spend": 0.05}]
    key_list = [{"id": kid, "token": "tok_hash_1", "key_alias": "n8n"}]

    out = resolve_key_display(stats_keys, key_list)

    assert out[0]["key_alias"] == "n8n"
    assert out[0]["id"] == kid  # aligned so the UI dedups the idle padding row
    # Usage untouched.
    assert out[0]["requests"] == 25
    assert out[0]["spend"] == 0.05
    # Pure: inputs not mutated.
    assert stats_keys[0]["key_alias"] == opaque
    assert stats_keys[0]["id"] == "spendhash_abc"


def test_resolve_key_display_token_hash_fallback():
    """When the opaque alias misses, join on spend-log id == key-list token hash."""
    stats_keys = [{"id": "tok_hash_1", "key_alias": None, "requests": 3, "spend": 0.01}]
    key_list = [{"id": _alias_id("lk-abc"), "token": "tok_hash_1", "key_alias": "default"}]

    out = resolve_key_display(stats_keys, key_list)

    assert out[0]["key_alias"] == "default"
    assert out[0]["id"] == _alias_id("lk-abc")


def test_resolve_key_display_unmatched_row_passes_through():
    """No key-list match (key deleted) → opaque alias kept, never worse (D-09)."""
    stats_keys = [{"id": "spendhash_x", "key_alias": "lk-deadbeef", "requests": 1, "spend": 0.0}]
    key_list = [{"id": _alias_id("lk-other"), "token": "tok_other", "key_alias": "n8n"}]

    out = resolve_key_display(stats_keys, key_list)

    assert out[0]["key_alias"] == "lk-deadbeef"
    assert out[0]["id"] == "spendhash_x"


def test_resolve_key_display_empty_key_list_is_noop_copy():
    """Key-list unavailable → rows pass through unchanged (degraded), as a copy."""
    stats_keys = [{"id": "h", "key_alias": "lk-1", "requests": 2, "spend": 0.0}]

    for kl in (None, []):
        out = resolve_key_display(stats_keys, kl)
        assert out == stats_keys
        assert out[0] is not stats_keys[0]  # never mutates / aliases the input
