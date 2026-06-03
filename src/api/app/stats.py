# SPDX-License-Identifier: Apache-2.0
"""Pure aggregation for GET /api/session/stats — no HTTP, fully unit-testable.

The route (Plan 03) fetches two `user_daily_activity` windows (current + prior)
and one budget block, then hands the raw LiteLLM v1.85.1 dicts to these pure
functions, which fold them into the page-ready contract the UI (Phase 13) renders
verbatim (D-03: server shapes a page-ready contract; the UI is a dumb renderer).

Contract shape produced by ``build_stats_contract`` (RESEARCH §4):

    {
      "range":   {start, end, days, compare:{start, end}},
      "totals":  {requests, tokens, spend, avg_cost_per_1k_req,
                  deltas:{requests_pct, tokens_pct, spend_pct,
                          avg_cost_per_1k_req_pct}},
      "series":  [{date, spend, requests}, ...],
      "models":  [{model, requests, input_tokens, output_tokens, total_tokens,
                   spend, spend_pct, last_used}, ...],
      "keys":    [{id, key_alias, requests, spend, spend_pct}, ...],  # spend desc
      "budget":  {current, max_budget, source, pct, has_budget},
      "capabilities": {token_split, per_model_last_used, deltas, per_key_spend},
    }

This is intentionally returned as a plain dict (the route uses JSONResponse with
``response_model=None``) — NOT a serializing pydantic response_model, which would
coerce the D-08 null-vs-0 semantics and the dynamically-keyed maps. The TypedDicts
below exist only for editor help.

D-08 null-vs-0: an UNAVAILABLE figure (e.g. last_used with no source, or a *_pct
whose denominator is 0/None) is ``None``; a figure that is genuinely ``0`` in the
window stays ``0``/``0.0``. Every denominator is guarded.
"""

from __future__ import annotations

from typing import Any, TypedDict

__all__ = ["aggregate_window", "compute_deltas", "build_stats_contract"]


class WindowAggregate(TypedDict):
    """Output of ``aggregate_window`` for a single daily-activity window."""

    requests: int
    tokens: int
    spend: float
    series: list[dict[str, Any]]
    models: list[dict[str, Any]]
    keys: list[dict[str, Any]]


class StatsContract(TypedDict):
    """Page-ready contract returned by ``build_stats_contract`` (editor help only)."""

    range: dict[str, Any]
    totals: dict[str, Any]
    series: list[dict[str, Any]]
    models: list[dict[str, Any]]
    keys: list[dict[str, Any]]
    budget: dict[str, Any]
    capabilities: dict[str, bool]


def _num(value: Any, default: float = 0) -> float:
    """Coerce a metric to a number, treating None/garbage as the (real-zero) default."""
    if value is None:
        return default
    try:
        return value if isinstance(value, (int, float)) else float(value)
    except (TypeError, ValueError):
        return default


def _safe_pct(numerator: float | None, denominator: float | None) -> float | None:
    """numerator/denominator with a None/0-denominator guard → None (D-08)."""
    if denominator is None or denominator == 0:
        return None
    if numerator is None:
        return None
    return numerator / denominator


def aggregate_window(data: dict[str, Any]) -> WindowAggregate:
    """Fold ONE daily-activity window into window totals + series + per-model/per-key.

    Window totals come from ``data["metadata"]`` (LiteLLM pre-aggregates the range).
    ``series`` is one entry per ``results[]`` day. Per-model and per-key metrics are
    summed ACROSS days from each ``results[].breakdown.models`` /
    ``results[].breakdown.api_keys`` (the breakdowns are per-day; the window total
    is the sum). Models/keys absent in-window are simply absent (no fabricated
    0-rows, RESEARCH §4 / D-08). Real ``0`` token splits stay ``0``.

    WR-04 — headline totals vs summed breakdown rows MAY DIVERGE by design. The
    ``requests``/``tokens``/``spend`` window totals come from LiteLLM's pre-aggregated
    ``metadata.total_*``, which counts EVERY request (including failed and model-less
    ones). The per-model breakdown only carries requests LiteLLM could attribute to a
    model, so ``sum(models[].requests)`` can be LESS than ``totals.requests`` for any
    window containing failed/model-less requests (e.g. the prior fixture: 4 total
    requests, 1 success attributed to ``veo-3.1-generate-preview``, 3 failed under
    ``api_keys`` with no ``models`` entry). The per-key breakdown DOES capture the
    failed requests, so ``sum(keys[].requests)`` tracks the total more closely. This
    is intentional: ``totals`` is the source of truth; the per-model table is an
    attribution view, not a reconciliation of the headline. ``test_stats.py``
    asserts this for the failed-request case so it is not mistaken for a regression.
    """
    metadata = data.get("metadata") or {}
    results = data.get("results") or []

    requests = int(_num(metadata.get("total_api_requests")))
    tokens = int(_num(metadata.get("total_tokens")))
    spend = _num(metadata.get("total_spend"))

    series: list[dict[str, Any]] = []
    model_acc: dict[str, dict[str, Any]] = {}
    key_acc: dict[str, dict[str, Any]] = {}

    for day in results:
        if not isinstance(day, dict):
            continue
        day_metrics = day.get("metrics") or {}
        series.append(
            {
                "date": day.get("date"),
                "spend": _num(day_metrics.get("spend")),
                "requests": int(_num(day_metrics.get("api_requests"))),
            }
        )

        breakdown = day.get("breakdown") or {}

        models = breakdown.get("models") or {}
        if isinstance(models, dict):
            for model_name, mblock in models.items():
                if not isinstance(mblock, dict):
                    continue
                m = mblock.get("metrics") or {}
                acc = model_acc.setdefault(
                    model_name,
                    {
                        "model": model_name,
                        "requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                        "spend": 0.0,
                    },
                )
                acc["requests"] += int(_num(m.get("api_requests")))
                acc["input_tokens"] += int(_num(m.get("prompt_tokens")))
                acc["output_tokens"] += int(_num(m.get("completion_tokens")))
                acc["total_tokens"] += int(_num(m.get("total_tokens")))
                acc["spend"] += _num(m.get("spend"))

        api_keys = breakdown.get("api_keys") or {}
        if isinstance(api_keys, dict):
            for key_hash, kblock in api_keys.items():
                if not isinstance(kblock, dict):
                    continue
                k = kblock.get("metrics") or {}
                kmeta = kblock.get("metadata") or {}
                acc = key_acc.setdefault(
                    key_hash,
                    {
                        "id": key_hash,
                        "key_alias": kmeta.get("key_alias"),
                        "requests": 0,
                        "spend": 0.0,
                    },
                )
                # Keep the first non-null alias we see for this hash.
                if acc.get("key_alias") is None and kmeta.get("key_alias") is not None:
                    acc["key_alias"] = kmeta.get("key_alias")
                acc["requests"] += int(_num(k.get("api_requests")))
                acc["spend"] += _num(k.get("spend"))

    return {
        "requests": requests,
        "tokens": tokens,
        "spend": spend,
        "series": series,
        "models": list(model_acc.values()),
        "keys": list(key_acc.values()),
    }


def _avg_cost_per_1k_req(spend: float | None, requests: float | None) -> float | None:
    """spend / requests * 1000, guarded for 0 requests → None (D-08)."""
    if not requests:
        return None
    return _num(spend) / requests * 1000


def compute_deltas(cur: dict[str, Any], prev: dict[str, Any]) -> dict[str, float | None]:
    """Period-over-period percentage change per metric, with a prior=0 → None guard.

    pct = (cur - prev) / prev. When ``prev`` is 0 (or missing) the change is
    undefined → ``None`` (not a crash, not +inf). The avg-cost delta compares the
    derived avg_cost_per_1k_req of each window (also guarded).
    """
    cur_req = _num(cur.get("requests"))
    prev_req = _num(prev.get("requests"))
    cur_tok = _num(cur.get("tokens"))
    prev_tok = _num(prev.get("tokens"))
    cur_spend = _num(cur.get("spend"))
    prev_spend = _num(prev.get("spend"))

    cur_avg = _avg_cost_per_1k_req(cur_spend, cur_req)
    prev_avg = _avg_cost_per_1k_req(prev_spend, prev_req)

    return {
        "requests_pct": _safe_pct(cur_req - prev_req, prev_req),
        "tokens_pct": _safe_pct(cur_tok - prev_tok, prev_tok),
        "spend_pct": _safe_pct(cur_spend - prev_spend, prev_spend),
        "avg_cost_per_1k_req_pct": (
            _safe_pct((cur_avg - prev_avg), prev_avg)
            if cur_avg is not None and prev_avg is not None
            else None
        ),
    }


def build_stats_contract(
    cur_agg: dict[str, Any],
    prev_agg: dict[str, Any],
    budget: dict[str, Any],
    last_used: dict[str, str],
    capabilities: dict[str, bool],
    range_meta: dict[str, Any],
) -> StatsContract:
    """Assemble the full page-ready stats contract from two aggregated windows.

    Args:
        cur_agg: ``aggregate_window`` output for the current window.
        prev_agg: ``aggregate_window`` output for the prior (compare) window.
        budget: {current, max_budget, source} from the LiteLLM user block.
        last_used: {model: iso_timestamp} from ``spend_logs_last_used`` (``{}`` to
            degrade — flips ``capabilities.per_model_last_used`` to False, D-08/D-09).
        capabilities: the {token_split, per_model_last_used, deltas, per_key_spend}
            defaults baked from the spike (12-SPIKE-FINDINGS.md, all True). This
            function may flip ``per_model_last_used`` to False when ``last_used`` is
            empty.
        range_meta: {start, end, days, compare:{start, end}} from the route.
    """
    capabilities = dict(capabilities)
    last_used = last_used or {}

    total_spend = _num(cur_agg.get("spend"))
    total_requests = int(_num(cur_agg.get("requests")))
    total_tokens = int(_num(cur_agg.get("tokens")))

    # Per-model: spend_pct guarded against total model spend; last_used from the map.
    raw_models = cur_agg.get("models") or []
    models_total_spend = sum(_num(m.get("spend")) for m in raw_models)
    models: list[dict[str, Any]] = []
    for m in raw_models:
        model_name = m.get("model")
        models.append(
            {
                "model": model_name,
                "requests": int(_num(m.get("requests"))),
                "input_tokens": int(_num(m.get("input_tokens"))),
                "output_tokens": int(_num(m.get("output_tokens"))),
                "total_tokens": int(_num(m.get("total_tokens"))),
                "spend": _num(m.get("spend")),
                "spend_pct": _safe_pct(_num(m.get("spend")), models_total_spend),
                "last_used": last_used.get(model_name),
            }
        )

    # last_used capability flips to False when no source data was supplied (D-09).
    capabilities["per_model_last_used"] = bool(last_used)

    # Per-key: spend_pct guarded; ranked by spend desc.
    raw_keys = cur_agg.get("keys") or []
    keys_total_spend = sum(_num(k.get("spend")) for k in raw_keys)
    keys: list[dict[str, Any]] = [
        {
            "id": k.get("id"),
            "key_alias": k.get("key_alias"),
            "requests": int(_num(k.get("requests"))),
            "spend": _num(k.get("spend")),
            "spend_pct": _safe_pct(_num(k.get("spend")), keys_total_spend),
        }
        for k in raw_keys
    ]
    keys.sort(key=lambda k: _num(k.get("spend")), reverse=True)

    # Budget: pct guarded for null/0 max_budget; has_budget = max_budget is not None.
    max_budget = budget.get("max_budget")
    current_spend = _num(budget.get("current"))
    budget_block = {
        "current": current_spend,
        "max_budget": max_budget,
        "source": budget.get("source"),
        "pct": _safe_pct(current_spend, max_budget),
        "has_budget": max_budget is not None,
    }

    totals = {
        "requests": total_requests,
        "tokens": total_tokens,
        "spend": total_spend,
        "avg_cost_per_1k_req": _avg_cost_per_1k_req(total_spend, total_requests),
        "deltas": compute_deltas(cur_agg, prev_agg),
    }

    return {
        "range": range_meta,
        "totals": totals,
        "series": cur_agg.get("series") or [],
        "models": models,
        "keys": keys,
        "budget": budget_block,
        "capabilities": capabilities,
    }
