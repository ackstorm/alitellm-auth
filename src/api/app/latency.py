# SPDX-License-Identifier: Apache-2.0
"""Pure aggregation for GET /api/session/latency — no HTTP, fully unit-testable.

The route (session.py::session_latency) fetches lean /spend/logs/v2 rows for the user
(under the caller's own LiteLLM key, bounded by pagination — newest pages first)
and hands them here. These functions fold the rows into a small, page-ready contract
that surfaces ONLY computed metrics — the raw rows (which carry messages/response/
metadata) are dropped at the fetch boundary and NEVER forwarded to the browser.

Contract shape produced by ``compute_latency_contract``:

    {
      "available": True,
      "sampled":   False,          # True if row_cap truncated the sample
      "row_count": 138,            # rows actually folded (post-cap)
      "window":    {start, end, days},
      "latency":   {p50_ms, p95_ms, p99_ms, avg_ms,
                    ttft_p50_ms, ttft_p95_ms,      # time-to-first-token (streaming)
                    tokens_per_sec_p50},           # output tok / wall-second
      "outcomes":  [{status, count}, ...],         # desc — for the request-outcome donut
      "by_model":  [{model, requests, failed, p50_ms, p95_ms}, ...],  # desc by requests
    }

Every latency figure is ``None`` when no row carries the datum (D-08 null-vs-0):
a non-streaming window has no TTFT; an all-error window has no durations.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

__all__ = ["compute_latency_contract", "percentile"]

# Cap how many rows we fold. /spend/logs pagination is a no-op, so LiteLLM may
# return the whole window at once; a heavy user over 7 days is thousands of rows.
# We percentile at most this many (label sampled=True past it) to bound CPU and
# signal that the figures are a sample, not the exhaustive window.
DEFAULT_ROW_CAP = 5000

# How many per-model rows to surface (ranked by request count).
_TOP_MODELS = 8


def percentile(sorted_vals: list[float], p: float) -> float | None:
    """Nearest-rank percentile of an ALREADY-SORTED list. None on empty.

    ``p`` in [0, 100]. Nearest-rank (not interpolated) is plenty for a latency
    headline and avoids float-index ambiguity. index = ceil(p/100 * n) - 1,
    clamped to [0, n-1].
    """
    n = len(sorted_vals)
    if n == 0:
        return None
    if p <= 0:
        return sorted_vals[0]
    idx = min(max(math.ceil(p / 100 * n) - 1, 0), n - 1)
    return sorted_vals[idx]


def _num(value: Any) -> float | None:
    """Coerce a metric to float, or None (bool rejected — it is not a measurement)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso(value: Any) -> datetime | None:
    """Parse a LiteLLM ISO timestamp (trailing ``Z`` tolerated). None on failure."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ttft_ms(row: dict[str, Any]) -> float | None:
    """Time-to-first-token = completionStartTime − startTime, in ms. None if absent.

    Only streaming responses carry completionStartTime; a null/absent field or an
    inverted delta (clock skew) yields None so it drops out of the percentile.
    """
    start = _parse_iso(row.get("startTime"))
    first = _parse_iso(row.get("completionStartTime"))
    if start is None or first is None:
        return None
    delta_ms = (first - start).total_seconds() * 1000.0
    return delta_ms if delta_ms >= 0 else None


def _tokens_per_sec(row: dict[str, Any]) -> float | None:
    """Output tokens per wall-second = completion_tokens / (duration_ms/1000)."""
    out = _num(row.get("completion_tokens"))
    dur = _num(row.get("request_duration_ms"))
    if not out or not dur or dur <= 0:
        return None
    return out / (dur / 1000.0)


def _row_model(row: dict[str, Any]) -> str:
    """Display model for a row: prefer the public group, fall back to the raw model."""
    return row.get("model_group") or row.get("model") or "unknown"


def _is_failure(status: Any) -> bool:
    """LiteLLM spend-log ``status`` is "success" | "failure" (not an HTTP code)."""
    return isinstance(status, str) and status.lower() != "success"


def compute_latency_contract(
    rows: list[dict[str, Any]] | None,
    window_meta: dict[str, Any],
    *,
    row_cap: int = DEFAULT_ROW_CAP,
    truncated: bool = False,
) -> dict[str, Any]:
    """Fold /spend/logs rows into the page-ready latency+outcomes contract.

    ``rows`` is the (lean) LiteLLM list (each a per-request dict). ``window_meta`` is
    the {start, end, days} echoed back to the UI. ``truncated`` is set by the caller
    when the chunked fetch already hit its row cap (the figures are a sample). Pure:
    no mutation of ``rows``, no I/O. A non-list / empty ``rows`` yields an available,
    all-empty contract.
    """
    safe = rows if isinstance(rows, list) else []
    # sampled = the fetch truncated, OR (safety net) we still hold more than the cap.
    sampled = truncated or len(safe) > row_cap
    if len(safe) > row_cap:
        safe = safe[:row_cap]

    durations: list[float] = []
    ttfts: list[float] = []
    tok_per_sec: list[float] = []
    outcomes: dict[str, int] = {}
    # model -> {requests, failed, durations[]}
    per_model: dict[str, dict[str, Any]] = {}

    for row in safe:
        if not isinstance(row, dict):
            continue
        model = _row_model(row)
        mrec = per_model.setdefault(model, {"requests": 0, "failed": 0, "durations": []})
        mrec["requests"] += 1

        status = row.get("status")
        label = status if isinstance(status, str) and status else "unknown"
        outcomes[label] = outcomes.get(label, 0) + 1
        if _is_failure(status):
            mrec["failed"] += 1

        dur = _num(row.get("request_duration_ms"))
        if dur is not None and dur >= 0:
            durations.append(dur)
            mrec["durations"].append(dur)

        ttft = _ttft_ms(row)
        if ttft is not None:
            ttfts.append(ttft)

        tps = _tokens_per_sec(row)
        if tps is not None:
            tok_per_sec.append(tps)

    durations.sort()
    ttfts.sort()
    tok_per_sec.sort()

    latency = {
        "p50_ms": percentile(durations, 50),
        "p95_ms": percentile(durations, 95),
        "p99_ms": percentile(durations, 99),
        "avg_ms": (sum(durations) / len(durations)) if durations else None,
        "ttft_p50_ms": percentile(ttfts, 50),
        "ttft_p95_ms": percentile(ttfts, 95),
        "tokens_per_sec_p50": percentile(tok_per_sec, 50),
    }

    outcome_rows = sorted(
        ({"status": s, "count": c} for s, c in outcomes.items()),
        key=lambda o: o["count"],
        reverse=True,
    )

    by_model = []
    for model, rec in per_model.items():
        mdurs = sorted(rec["durations"])
        by_model.append(
            {
                "model": model,
                "requests": rec["requests"],
                "failed": rec["failed"],
                "p50_ms": percentile(mdurs, 50),
                "p95_ms": percentile(mdurs, 95),
            }
        )
    by_model.sort(key=lambda m: m["requests"], reverse=True)

    return {
        "available": True,
        "sampled": sampled,
        "row_count": len(safe),
        "window": window_meta,
        "latency": latency,
        "outcomes": outcome_rows,
        "by_model": by_model[:_TOP_MODELS],
    }
