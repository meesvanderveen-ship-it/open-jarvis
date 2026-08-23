from bot.phase_d6_btc_gap_fill_runner import (
    build_btc_gap_fill_runner_plan,
    build_candidate_validator_summary,
    build_master_packet_v14,
    build_preflight_v4,
    build_quality_summary_v14,
    select_btc_gap_rows,
)


def _command_plan() -> dict:
    return {
        "safe_rows": [
            {
                "ticker": "BTC-USDC",
                "timeframe": "1D",
                "gap_start": 100,
                "gap_end_exclusive": 300,
                "gap_end_exclusive_iso": "1970-01-01T00:05:00Z",
                "missing_candle_count": 2,
                "chunks_needed": 1,
                "candles_path": "research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json",
            },
            {
                "ticker": "BTC-USDC",
                "timeframe": "4H",
                "gap_start": 400,
                "gap_end_exclusive": 800,
                "gap_end_exclusive_iso": "1970-01-01T00:13:20Z",
                "missing_candle_count": 4,
                "chunks_needed": 1,
                "candles_path": "research_data/coinbase/candles/product=BTC-USDC/timeframe=4H/study_window=3y.json",
            },
        ],
        "blocked_rows": [
            {
                "ticker": "BTC-USDC",
                "timeframe": "1H",
                "chunks_needed": 67,
            }
        ],
    }


def test_select_btc_gap_rows_smallest_first() -> None:
    rows = select_btc_gap_rows(command_plan=_command_plan(), timeframes=["1D", "4H"])

    assert [row["timeframe"] for row in rows] == ["1D", "4H"]


def test_runner_plan_keeps_fetch_off_and_records_blocked_1h(tmp_path) -> None:
    plan = build_btc_gap_fill_runner_plan(command_plan=_command_plan(), candidate_root=tmp_path / "candidate")

    assert plan["fetch_executed"] is False
    assert plan["merge_executed"] is False
    assert plan["state_write_performed"] is False
    assert len(plan["selected_rows"]) == 2
    assert plan["blocked_btc_1h_rows"][0]["chunks_needed"] == 67
    assert plan["coinbase_public_market_data_call_performed"] is False


def test_validator_summary_pending_before_fetch(tmp_path) -> None:
    plan = build_btc_gap_fill_runner_plan(command_plan=_command_plan(), candidate_root=tmp_path / "candidate")
    summary = build_candidate_validator_summary(runner_result=None, runner_plan=plan)

    assert summary["pending_count"] == 2
    assert summary["pass_count"] == 0
    assert summary["no_live_action"] is True


def test_master_packet_keeps_routes_blocked(tmp_path) -> None:
    plan = build_btc_gap_fill_runner_plan(command_plan=_command_plan(), candidate_root=tmp_path / "candidate")
    validator = build_candidate_validator_summary(runner_result=None, runner_plan=plan)
    quality = {
        **build_quality_summary_v14(),
        "summary": {"quality_report_count": 1, "good_count": 0, "warning_count": 1, "invalid_count": 0},
    }
    preflight = build_preflight_v4(quality_summary=quality, runner_result=None)
    master = build_master_packet_v14(
        validator_summary=validator,
        runner_plan=plan,
        runner_result=None,
        quality_summary=quality,
        backtest_readiness={"status": "ready"},
        preflight_v4=preflight,
    )

    assert master["all_ticker_24h_status"] == "blocked"
    assert master["parameter_change_allowed"] is False
    assert master["learning_to_execution_enabled"] is False
