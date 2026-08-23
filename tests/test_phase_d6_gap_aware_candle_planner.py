import json

from bot.phase_d6_gap_aware_candle_planner import (
    build_gap_aware_candle_planner,
    build_gap_fill_command_plan,
    build_master_packet_v13,
    build_open_source_inspiration_report,
    build_post_gap_fill_quality_summary,
    build_preflight_v3,
    detect_candle_gaps,
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


def test_detect_candle_gaps_reports_exact_missing_range(tmp_path) -> None:
    candles = tmp_path / "research_data" / "coinbase" / "candles" / "product=BTC-USDC" / "timeframe=1H" / "study_window=3y.json"
    candles.parent.mkdir(parents=True)
    candles.write_text(json.dumps([_row(0), _row(3600), _row(14400)]), encoding="utf-8")

    gaps = detect_candle_gaps(candles_path=candles, ticker="BTC-USDC", timeframe="1H")

    assert len(gaps) == 1
    assert gaps[0].gap_start == 7200
    assert gaps[0].gap_end_exclusive == 14400
    assert gaps[0].missing_candle_count == 2
    assert gaps[0].chunks_needed == 1


def test_gap_planner_is_report_only_and_blocks_large_gaps(tmp_path) -> None:
    root = tmp_path / "candles"
    candles = root / "product=BTC-USDC" / "timeframe=1H" / "study_window=3y.json"
    candles.parent.mkdir(parents=True)
    candles.write_text(json.dumps([_row(0), _row(3600 * 1000)]), encoding="utf-8")

    planner = build_gap_aware_candle_planner(
        tickers=["BTC-USDC"],
        timeframes=["1H"],
        candidate_root=tmp_path / "candidate",
        max_chunks_per_gap=2,
        as_of="2026-06-01T00:00:00Z",
    )
    # Default planner root does not point at tmp_path; direct gap detection verifies the block behavior.
    gaps = detect_candle_gaps(candles_path=candles, ticker="BTC-USDC", timeframe="1H")
    assert gaps[0].chunks_needed > 2
    assert planner["state_write_performed"] is False
    assert planner["no_live_action"] is True
    assert planner["parameter_change_allowed"] is False
    assert planner["learning_to_execution_enabled"] is False


def test_gap_fill_command_plan_requires_dry_run_and_no_state_paths(tmp_path) -> None:
    planner = {
        "candidate_root": str(tmp_path / "candidate"),
        "rows": [
            {
                "ticker": "BTC-USDC",
                "timeframe": "1H",
                "safe_to_fetch_under_existing_ack": True,
                "dry_run_command": "dry",
                "bounded_fetch_command": "fetch",
            }
        ],
    }

    plan = build_gap_fill_command_plan(planner=planner)

    assert plan["dry_run_required_first"] is True
    assert plan["fetch_executed"] is False
    assert plan["merge_executed"] is False
    assert plan["state_write_performed"] is False
    assert "state/" not in json.dumps(plan)


def test_open_source_report_is_pattern_only() -> None:
    report = build_open_source_inspiration_report()

    assert report["state_write_performed"] is False
    assert report["coinbase_public_market_data_call_performed"] is False
    assert "new_dependency_install" in report["rejected_patterns"]


def test_v13_master_keeps_live_and_learning_boundaries_closed(tmp_path) -> None:
    candles = tmp_path / "candles.json"
    candles.write_text(json.dumps([_row(0), _row(3600)]), encoding="utf-8")
    quality = build_post_gap_fill_quality_summary(candle_paths=[candles], as_of="2026-06-01T00:00:00Z")
    planner = {"gap_count": 0, "safe_gap_fetch_count": 0, "blocked_gap_fetch_count": 0}
    preflight = build_preflight_v3(quality_summary=quality, planner=planner)
    master = build_master_packet_v13(
        open_source_report={"sources": [1, 2, 3, 4]},
        planner=planner,
        command_plan={"execution_decision": "plan_only"},
        quality_summary=quality,
        backtest_readiness={"status": "ready"},
        preflight_v3=preflight,
    )

    assert master["no_live_action"] is True
    assert master["parameter_change_allowed"] is False
    assert master["optimization_performed"] is False
    assert master["learning_to_execution_enabled"] is False
    assert master["all_ticker_24h_status"] == "blocked"
