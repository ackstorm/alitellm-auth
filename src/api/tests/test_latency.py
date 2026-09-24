# SPDX-License-Identifier: Apache-2.0
"""Pure-unit tests for app/latency.py (no HTTP).

compute_latency_contract folds raw /spend/logs rows into the page-ready latency +
request-outcome contract. These tests build synthetic rows (the same shape LiteLLM
emits: request_duration_ms, status, model_group, startTime/completionStartTime,
completion_tokens) and assert the percentiles, status split, TTFT, throughput,
per-model fold, sampling cap, and the null-vs-0 degradation.
"""

from app.latency import DEFAULT_ROW_CAP, compute_latency_contract, percentile

_WINDOW = {"start": "2026-07-05", "end": "2026-07-11", "days": 7}


def _row(*, dur_ms, status="success", model="gemini/flash", out_tokens=100, ttft_ms=None):
    """One synthetic spend-log row. ttft_ms=None → no completionStartTime (non-stream)."""
    row = {
        "request_duration_ms": dur_ms,
        "status": status,
        "model_group": model,
        "completion_tokens": out_tokens,
        "startTime": "2026-07-08T09:00:00Z",
        # 09:00:00 + secs — keep it simple: only sub-minute durations/ttfts in tests.
        "endTime": f"2026-07-08T09:00:{(dur_ms or 0) / 1000.0:06.3f}Z",
    }
    # LiteLLM defaults completionStartTime to endTime when nothing streamed.
    row["completionStartTime"] = row["endTime"]
    if ttft_ms is not None:
        # completionStartTime = startTime + ttft_ms
        row["completionStartTime"] = f"2026-07-08T09:00:{ttft_ms / 1000.0:06.3f}Z"
    return row


# ---------------------------------------------------------------------------
# percentile
# ---------------------------------------------------------------------------


def test_percentile_empty_is_none():
    assert percentile([], 50) is None


def test_percentile_nearest_rank():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert percentile(vals, 50) == 5.0  # ceil(0.5*10)=5 → idx 4
    assert percentile(vals, 95) == 10.0  # ceil(0.95*10)=10 → idx 9
    assert percentile(vals, 99) == 10.0
    assert percentile(vals, 0) == 1.0


def test_percentile_single_value():
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 99) == 42.0


# ---------------------------------------------------------------------------
# compute_latency_contract — happy path
# ---------------------------------------------------------------------------


def test_contract_latency_percentiles():
    rows = [_row(dur_ms=float(x)) for x in range(100, 1100, 100)]  # 100..1000
    c = compute_latency_contract(rows, _WINDOW)
    assert c["available"] is True
    assert c["sampled"] is False
    assert c["row_count"] == 10
    assert c["window"] == _WINDOW
    assert c["latency"]["p50_ms"] == 500.0
    assert c["latency"]["p95_ms"] == 1000.0
    assert c["latency"]["avg_ms"] == 550.0


def test_contract_status_split_and_outcomes():
    rows = [_row(dur_ms=100, status="success")] * 9 + [_row(dur_ms=100, status="failure")]
    c = compute_latency_contract(rows, _WINDOW)
    outcomes = {o["status"]: o["count"] for o in c["outcomes"]}
    assert outcomes == {"success": 9, "failure": 1}
    # outcomes are ranked by count desc — success first
    assert c["outcomes"][0]["status"] == "success"


def test_contract_by_model_fold_and_failures():
    rows = [
        _row(dur_ms=200, model="a", status="success"),
        _row(dur_ms=400, model="a", status="failure"),
        _row(dur_ms=600, model="b", status="success"),
    ]
    c = compute_latency_contract(rows, _WINDOW)
    by_model = {m["model"]: m for m in c["by_model"]}
    assert by_model["a"]["requests"] == 2
    assert by_model["a"]["failed"] == 1
    assert by_model["b"]["requests"] == 1
    assert by_model["b"]["failed"] == 0
    # ranked by request count desc → 'a' (2) before 'b' (1)
    assert c["by_model"][0]["model"] == "a"


def test_contract_ttft_and_throughput():
    # duration 1000ms, 200 output tokens → 200 tok/s; ttft 300ms
    rows = [_row(dur_ms=1000, out_tokens=200, ttft_ms=300)]
    c = compute_latency_contract(rows, _WINDOW)
    assert c["latency"]["ttft_p50_ms"] == 300.0
    assert c["latency"]["tokens_per_sec_p50"] == 200.0


def test_contract_no_ttft_when_non_streaming():
    rows = [_row(dur_ms=1000, ttft_ms=None)]
    c = compute_latency_contract(rows, _WINDOW)
    assert c["latency"]["ttft_p50_ms"] is None  # D-08: absent, not 0


def test_contract_ttft_ignores_mcp_and_non_streamed_rows():
    """Prod bug: TTFT 2 ms next to 3.55 s avg. MCP rows (~0 ms) and non-streamed
    rows (completionStartTime == endTime) must not enter the TTFT pool."""
    rows = [_row(dur_ms=5, model="MCP: list_tools", ttft_ms=2) for _ in range(5)]
    rows.append(_row(dur_ms=3000))  # non-streamed: would read as 3000 ms TTFT
    rows.append(_row(dur_ms=2000, ttft_ms=800))  # the only real TTFT
    c = compute_latency_contract(rows, _WINDOW)
    assert c["latency"]["ttft_p50_ms"] == 800.0


# ---------------------------------------------------------------------------
# degradation + bounds
# ---------------------------------------------------------------------------


def test_contract_empty_rows_available_but_null():
    c = compute_latency_contract([], _WINDOW)
    assert c["available"] is True
    assert c["row_count"] == 0
    assert c["latency"]["p50_ms"] is None
    assert c["outcomes"] == []
    assert c["by_model"] == []


def test_contract_non_list_degrades():
    c = compute_latency_contract(None, _WINDOW)  # type: ignore[arg-type]
    assert c["available"] is True
    assert c["row_count"] == 0


def test_contract_row_cap_sets_sampled():
    rows = [_row(dur_ms=100)] * (DEFAULT_ROW_CAP + 50)
    c = compute_latency_contract(rows, _WINDOW)
    assert c["sampled"] is True
    assert c["row_count"] == DEFAULT_ROW_CAP


def test_contract_truncated_flag_sets_sampled():
    # The fetch already capped (chunked lean fetch) → truncated=True must surface as
    # sampled even though the row list is under the cap.
    c = compute_latency_contract([_row(dur_ms=100)], _WINDOW, truncated=True)
    assert c["sampled"] is True
    assert c["row_count"] == 1


def test_contract_failed_row_missing_duration_still_counts_outcome():
    # A failed request with no duration must still register in outcomes/by_model
    # (it just contributes no latency sample).
    rows = [
        _row(dur_ms=None, status="failure", model="x"),  # type: ignore[arg-type]
        _row(dur_ms=500, status="success", model="x"),
    ]
    c = compute_latency_contract(rows, _WINDOW)
    outcomes = {o["status"]: o["count"] for o in c["outcomes"]}
    assert outcomes == {"failure": 1, "success": 1}
    x = next(m for m in c["by_model"] if m["model"] == "x")
    assert x["requests"] == 2
    assert x["failed"] == 1
    assert x["p50_ms"] == 500.0  # only the one row with a duration
