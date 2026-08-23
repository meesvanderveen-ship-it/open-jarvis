from datetime import datetime, timezone

from bot.phase_d6_rate_limited_public_fetch import (
    RateLimitPolicy,
    build_rate_limited_fetch_plan,
    classify_fetch_error,
    execute_rate_limited_fetch,
)


def _raw(start: int) -> dict:
    return {"start": start, "open": "1", "high": "2", "low": "1", "close": "2", "volume": "1"}


class FakeClient:
    def __init__(self, *, failures: int = 0, empty: bool = False) -> None:
        self.failures = failures
        self.empty = empty
        self.calls = []

    def get_public_candles(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary_rate_limit")
        if self.empty:
            return {"candles": []}
        return {"candles": [_raw(int(kwargs["end"]))]}


def test_rate_limited_plan_refuses_large_one_minute_batch(tmp_path) -> None:
    plan = build_rate_limited_fetch_plan(
        ticker="BTC-USDC",
        timeframe="4H",
        chunks=[{"start": 1, "end_exclusive": 2}, {"start": 2, "end_exclusive": 3}],
        candidate_root=tmp_path,
        run_id="x",
        policy=RateLimitPolicy(max_requests_per_minute=1),
    )

    assert "planned_requests_exceed_one_minute_policy" in plan["blockers"]
    assert plan["state_write_performed"] is False


def test_rate_limited_fetch_retries_then_writes_candidate(tmp_path) -> None:
    sleeps = []
    plan = build_rate_limited_fetch_plan(
        ticker="BTC-USDC",
        timeframe="4H",
        chunks=[{"start": 1761408000, "end_exclusive": 1761422400}],
        candidate_root=tmp_path,
        run_id="x",
        policy=RateLimitPolicy(min_delay_seconds=0, max_retries_per_chunk=2, retry_budget_total=2, jitter_seconds=0),
    )

    result = execute_rate_limited_fetch(
        plan=plan,
        client=FakeClient(failures=1),
        sleep_fn=sleeps.append,
        now_fn=lambda: 0.0,
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "rate_limited_public_fetch_ready"
    assert result["retry_count"] == 1
    assert result["candidate_count"] == 1
    assert result["partial_candidate_quarantined"] is False
    assert len(sleeps) == 1


def test_zero_candle_response_quarantines_candidate(tmp_path) -> None:
    plan = build_rate_limited_fetch_plan(
        ticker="BTC-USDC",
        timeframe="4H",
        chunks=[{"start": 1761408000, "end_exclusive": 1761422400}],
        candidate_root=tmp_path,
        run_id="x",
        policy=RateLimitPolicy(min_delay_seconds=0),
    )

    result = execute_rate_limited_fetch(
        plan=plan,
        client=FakeClient(empty=True),
        sleep_fn=lambda _: None,
        now_fn=lambda: 0.0,
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "rate_limited_public_fetch_blocked"
    assert result["partial_candidate_quarantined"] is True
    assert result["zero_candle_response_count"] == 1
    assert result["stop_reason"] == "zero_candle_response_fail_closed"
    assert result["next_resume_chunk_index"] == 1


def test_consecutive_errors_fail_closed_with_resume_index(tmp_path) -> None:
    plan = build_rate_limited_fetch_plan(
        ticker="BTC-USDC",
        timeframe="1H",
        chunks=[
            {"chunk_index": 0, "start": 1000, "end_exclusive": 2000},
            {"chunk_index": 1, "start": 2000, "end_exclusive": 3000},
        ],
        candidate_root=tmp_path,
        run_id="x",
        policy=RateLimitPolicy(
            min_delay_seconds=0,
            max_retries_per_chunk=4,
            retry_budget_total=4,
            max_consecutive_errors=2,
            jitter_seconds=0,
        ),
    )

    result = execute_rate_limited_fetch(
        plan=plan,
        client=FakeClient(failures=3),
        sleep_fn=lambda _: None,
        now_fn=lambda: 0.0,
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "rate_limited_public_fetch_blocked"
    assert result["fail_closed"] is True
    assert result["stop_reason"] == "retry_budget_or_consecutive_error_limit_reached"
    assert result["next_resume_chunk_index"] == 1
    assert result["resume_token"]["requires_operator_review"] is True


def test_rate_limited_plan_refuses_per_run_budget_excess(tmp_path) -> None:
    plan = build_rate_limited_fetch_plan(
        ticker="BTC-USDC",
        timeframe="1H",
        chunks=[{"start": 1, "end_exclusive": 2}, {"start": 2, "end_exclusive": 3}],
        candidate_root=tmp_path,
        run_id="x",
        policy=RateLimitPolicy(max_requests_per_minute=10, max_requests_per_run=1),
    )

    assert "planned_requests_exceed_run_policy" in plan["blockers"]


def test_fetch_error_classification() -> None:
    assert classify_fetch_error(RuntimeError("429 too many requests")) == "rate_limit_error"
    assert classify_fetch_error(RuntimeError("temporary DNS failure")) == "network_error"
    assert classify_fetch_error("", zero_candle=True) == "zero_candle_response"
