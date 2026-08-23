import json

from bot.phase_d6_24h_readiness_v11 import (
    build_exploratory_backtest_result_bundle,
    build_preflight_runner_report,
    build_readiness_master_v11,
    build_recent_tail_refresh_plan,
)


def _write_candles(path, ticker="BTC-USDC", timeframe="1D"):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx in range(30):
        rows.append(
            {
                "product_id": ticker,
                "timeframe": timeframe,
                "start": 1700000000 + idx * 86400,
                "open": "100",
                "high": "110",
                "low": "90",
                "close": str(100 + idx),
                "volume": "1",
            }
        )
    path.write_text(json.dumps(rows), encoding="utf-8")


def _coverage(candle_path):
    return {
        "rows": [
            {
                "ticker": "BTC-USDC",
                "timeframe": "1D",
                "cached_data_present": True,
                "cached_candles_path": str(candle_path),
            }
        ]
    }


def _quality():
    return {
        "rows": [
            {
                "product_id": "BTC-USDC",
                "timeframe": "1D",
                "quality_class": "usable_with_warnings",
                "warnings": ["stale_last_candle"],
                "fatal_errors": [],
                "gap_count": 0,
            }
        ]
    }


def test_recent_tail_plan_does_not_fetch_with_start_chunk_fetcher(tmp_path) -> None:
    report = build_recent_tail_refresh_plan(coverage_report={"rows": [{}]}, quality_report=_quality(), as_of="2026-06-01T00:00:00Z")

    assert report["stale_row_count"] == 1
    assert report["existing_fetcher_tail_capable"] is False
    assert report["fetch_executed"] is False
    assert report["coinbase_public_market_data_call_performed"] is False
    assert report["state_write_performed"] is False


def test_exploratory_bundle_runs_bounded_subset_without_parameter_evidence(tmp_path) -> None:
    candle_path = tmp_path / "candles.json"
    _write_candles(candle_path)
    report = build_exploratory_backtest_result_bundle(
        coverage_report=_coverage(candle_path),
        quality_report=_quality(),
        tickers=["BTC-USDC"],
        baselines=["buy_hold", "simple_ma"],
    )

    assert report["selected_row_count"] == 1
    assert report["result_count"] == 2
    assert report["exploratory_backtest_executed"] is True
    assert report["normal_backtest_executed"] is False
    assert report["parameter_evidence_created"] is False
    assert report["optimization_performed"] is False
    assert report["ranking_performed"] is False
    assert report["learning_to_execution_enabled"] is False
    assert {row["mode"] for row in report["results"]} == {"exploratory_only"}


def test_preflight_runner_keeps_routes_gated_or_blocked() -> None:
    local_safety = {
        "open_orders": {"summary": {"open_orders": 0}},
        "function_audit_stdout": "Status:    ok_observe_only\n",
        "d3": {"status": "d3_no_manageable_open_position"},
        "state_hashes": {"state/open_orders.json": "abc"},
    }
    report = build_preflight_runner_report(
        local_safety=local_safety,
        readiness_report={"status": "ready"},
        as_of="2026-06-01T00:00:00Z",
    )

    assert report["preflight_result"] == "pass_local_non_live_checks"
    assert report["route_matrix"]["btc_usdc_only"]["status"] == "ack_gated_after_fresh_preflight"
    assert report["route_matrix"]["all_ticker_24h"]["status"] == "blocked"
    assert report["no_live_action"] is True
    assert report["contains_live_instructions"] is False


def test_master_v11_preserves_boundaries(tmp_path) -> None:
    tail = build_recent_tail_refresh_plan(coverage_report={"rows": [{}]}, quality_report=_quality(), as_of="2026-06-01T00:00:00Z")
    candle_path = tmp_path / "candles.json"
    _write_candles(candle_path)
    exploratory = build_exploratory_backtest_result_bundle(
        coverage_report=_coverage(candle_path),
        quality_report=_quality(),
        tickers=["BTC-USDC"],
        baselines=["buy_hold"],
    )
    preflight = build_preflight_runner_report(
        local_safety={
            "open_orders": {"summary": {"open_orders": 0}},
            "function_audit_stdout": "Status:    ok_observe_only\n",
            "d3": {"status": "d3_no_manageable_open_position"},
        },
        readiness_report={"status": "ready"},
        as_of="2026-06-01T00:00:00Z",
    )
    report = build_readiness_master_v11(
        tail_plan=tail,
        exploratory_bundle=exploratory,
        preflight_report=preflight,
        as_of="2026-06-01T00:00:00Z",
    )

    assert report["exploratory_backtest_status"] == "bounded_subset_completed"
    assert report["all_ticker_24h_status"] == "blocked"
    assert report["parameter_review_approved"] is False
    assert report["parameter_values_changed"] is False
    assert report["optimization_performed"] is False
    assert report["learning_to_execution_enabled"] is False
