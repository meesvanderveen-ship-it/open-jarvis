from bot.phase_d6_coverage_backtest_decision import build_coverage_backtest_decision


def _coverage_report():
    rows = []
    for ticker in ("BTC-USDC", "XRP-USDC"):
        for timeframe in ("1D", "1H", "4H"):
            rows.append(
                {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "cached_data_present": True,
                    "cached_candles_path": (
                        f"research_data/coinbase/candles/product={ticker}/"
                        f"timeframe={timeframe}/study_window=3y.json"
                    ),
                    "candle_count": 700,
                }
            )
    return {
        "status": "multi_ticker_dataset_coverage_plan_refresh_v9_ready",
        "configured_ticker_count": 2,
        "rows": rows,
    }


def _quality_report():
    return {
        "status": "post_fetch_dataset_quality_summary_v9_ready",
        "summary": {"quality_report_count": 6, "warning_count": 6, "good_count": 0},
        "rows": [
            {
                "product_id": ticker,
                "timeframe": timeframe,
                "quality_class": "usable_with_warnings",
                "status": "usable_with_warnings",
            }
            for ticker in ("BTC-USDC", "XRP-USDC")
            for timeframe in ("1D", "1H", "4H")
        ],
    }


def test_complete_warning_only_coverage_defers_normal_backtests() -> None:
    report = build_coverage_backtest_decision(
        coverage_report=_coverage_report(),
        quality_report=_quality_report(),
        expansion_report={"status": "bounded_candle_coverage_expansion_v9_ready"},
    )

    assert report["coverage_completeness"]["complete_required_rows"] is True
    assert report["coverage_completeness"]["missing_row_count"] == 0
    assert report["dataset_quality_decision"]["all_cached_rows_warning_only"] is True
    assert report["backtest_decision"]["normal_backtests_deferred"] is True
    assert report["backtest_decision"]["normal_backtest_executed"] is False
    assert report["backtest_decision"]["exploratory_backtest_executed"] is False
    assert report["backtest_decision"]["parameter_evidence_created"] is False


def test_xrp_1h_diagnostic_is_resolved_when_row_exists() -> None:
    report = build_coverage_backtest_decision(
        coverage_report=_coverage_report(),
        quality_report=_quality_report(),
    )

    assert report["xrp_usdc_1h_diagnostic"]["status"] == "resolved"
    assert report["xrp_usdc_1h_diagnostic"]["merged_candle_count"] == 700


def test_command_plan_is_research_only_and_does_not_touch_state() -> None:
    report = build_coverage_backtest_decision(
        coverage_report=_coverage_report(),
        quality_report=_quality_report(),
    )

    assert report["research_only"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["parameter_review_approved"] is False
    assert report["parameter_values_changed"] is False
    assert report["optimization_performed"] is False
    assert report["ranking_performed"] is False
    assert report["learning_to_execution_enabled"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["exploratory_only_command_plan"]
    assert all("state/" not in row["output_path"] for row in report["exploratory_only_command_plan"])
    assert all(row["run_now"] is False for row in report["exploratory_only_command_plan"])
