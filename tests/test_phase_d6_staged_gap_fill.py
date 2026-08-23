import json
from datetime import datetime, timezone

from bot.phase_d6_staged_gap_fill import (
    build_backtest_readiness_v15,
    build_master_packet_v15,
    build_preflight_v5,
    build_staged_gap_fill_plan,
    execute_staged_gap_fill,
    select_subruns_for_execution,
)


def _row(start: int, timeframe: str = "1H") -> dict:
    return {
        "product_id": "BTC-USDC",
        "timeframe": timeframe,
        "start": start,
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100",
        "volume": "1",
    }


def _command_plan(existing_path: str, *, timeframe: str = "1H", missing: int = 701) -> dict:
    step = 3600 if timeframe == "1H" else 86400
    return {
        "safe_rows": [],
        "blocked_rows": [
            {
                "ticker": "BTC-USDC",
                "timeframe": timeframe,
                "gap_start": step,
                "gap_end_exclusive": step + missing * step,
                "missing_candle_count": missing,
                "chunks_needed": 3,
                "candles_path": existing_path,
            }
        ],
    }


class FakeClient:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty
        self.calls = []

    def get_public_candles(self, **kwargs):
        self.calls.append(kwargs)
        if self.empty:
            return {"candles": []}
        start = int(kwargs["start"])
        end = int(kwargs["end"])
        granularity = kwargs["granularity"]
        step = 3600 if granularity == "ONE_HOUR" else 86400
        candles = [_row(ts, "1H" if step == 3600 else "1D") for ts in range(start + step, end + step, step)]
        return {"candles": candles}


def test_plan_splits_large_1h_gap_into_bounded_subruns(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps([_row(0), _row(702 * 3600)]), encoding="utf-8")

    plan = build_staged_gap_fill_plan(
        command_plan=_command_plan(str(existing)),
        candidate_root=tmp_path / "candidate",
        subrun_max_chunks=2,
    )

    assert plan["subrun_count"] == 2
    assert [row["chunks_requested"] for row in plan["subruns"]] == [2, 1]
    assert plan["subruns"][0]["expected_candle_count"] == 700
    assert plan["subruns"][1]["expected_candle_count"] == 1
    assert plan["coinbase_public_market_data_call_performed"] is False
    assert plan["state_write_performed"] is False


def test_select_subruns_fails_closed_when_execution_budget_exceeded(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps([_row(0), _row(702 * 3600)]), encoding="utf-8")
    plan = build_staged_gap_fill_plan(
        command_plan=_command_plan(str(existing)),
        candidate_root=tmp_path / "candidate",
        subrun_max_chunks=2,
        execution_max_chunks=1,
    )

    try:
        select_subruns_for_execution(plan)
    except ValueError as exc:
        assert "selected_subruns_exceed_execution_chunk_budget" in str(exc)
    else:
        raise AssertionError("expected budget failure")


def test_execute_staged_gap_fill_merges_only_after_exact_validation(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps([_row(0), _row(3 * 3600)]), encoding="utf-8")
    plan = build_staged_gap_fill_plan(
        command_plan=_command_plan(str(existing), missing=2),
        candidate_root=tmp_path / "candidate",
        subrun_max_chunks=1,
    )

    result = execute_staged_gap_fill(
        plan=plan,
        client=FakeClient(),
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    merged = json.loads(existing.read_text(encoding="utf-8"))
    assert result["status"] == "staged_gap_fill_result_ready"
    assert result["updated_file_count"] == 1
    assert [row["start"] for row in merged] == [0, 3600, 7200, 10800]
    assert result["state_write_performed"] is False


def test_execute_staged_gap_fill_stops_on_empty_candidate(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps([_row(0), _row(3 * 3600)]), encoding="utf-8")
    plan = build_staged_gap_fill_plan(
        command_plan=_command_plan(str(existing), missing=2),
        candidate_root=tmp_path / "candidate",
        subrun_max_chunks=1,
    )

    result = execute_staged_gap_fill(
        plan=plan,
        client=FakeClient(empty=True),
        fetched_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "staged_gap_fill_result_blocked"
    assert result["updated_file_count"] == 0
    assert "stopped_after_validation_failure" in result["stop_reason"]
    assert result["result_rows"][0]["validation"]["validator_pass"] is False


def test_v15_readiness_keeps_routes_blocked_until_quality_resolved(tmp_path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text(json.dumps([_row(0), _row(3 * 3600)]), encoding="utf-8")
    plan = build_staged_gap_fill_plan(command_plan=_command_plan(str(existing), missing=2), candidate_root=tmp_path / "candidate")
    quality = {"summary": {"quality_report_count": 54, "good_count": 0, "warning_count": 54, "invalid_count": 0}}
    backtest = build_backtest_readiness_v15(quality_summary=quality, staged_result=None)
    preflight = build_preflight_v5(quality_summary=quality, staged_plan=plan, staged_result=None)
    master = build_master_packet_v15(
        staged_plan=plan,
        staged_result=None,
        quality_summary=quality,
        backtest_readiness=backtest,
        preflight_v5=preflight,
    )

    assert backtest["normal_backtests_deferred"] is True
    assert preflight["route_matrix"]["all_ticker_24h"] == "blocked"
    assert master["btc_usdc_only_24h_status"] == "blocked_until_btc_gap_quality_is_resolved_then_ack_gated"
    assert master["parameter_values_changed"] is False
