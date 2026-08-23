from bot.phase_d6_24h_readiness_sprint import (
    build_24h_preflight_architecture,
    build_24h_readiness_master_v10,
    build_dataset_quality_warning_diagnostic,
    build_exploratory_backtest_readiness,
)


def _coverage():
    rows = []
    for ticker in ("BTC-USDC", "ETH-USDC"):
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
                }
            )
    return {"status": "coverage_ready", "rows": rows}


def _quality():
    return {
        "status": "quality_ready",
        "rows": [
            {
                "product_id": ticker,
                "timeframe": timeframe,
                "quality_class": "usable_with_warnings",
                "warnings": ["stale_last_candle"],
                "fatal_errors": [],
                "gap_count": 0,
            }
            for ticker in ("BTC-USDC", "ETH-USDC")
            for timeframe in ("1D", "1H", "4H")
        ],
    }


def test_warning_diagnostic_classifies_stale_warning_only_rows() -> None:
    report = build_dataset_quality_warning_diagnostic(quality_report=_quality(), as_of="2026-06-01T00:00:00Z")

    assert report["quality_report_count"] == 6
    assert report["warning_counts"] == {"stale_last_candle": 6}
    assert report["fatal_error_row_count"] == 0
    assert report["gap_row_count"] == 0
    assert report["diagnostic_conclusion"]["normal_backtests_as_parameter_evidence"] is False
    assert report["parameter_review_approved"] is False
    assert report["learning_to_execution_enabled"] is False


def test_exploratory_backtest_readiness_plans_without_running() -> None:
    report = build_exploratory_backtest_readiness(
        coverage_report=_coverage(),
        quality_report=_quality(),
        as_of="2026-06-01T00:00:00Z",
    )

    assert report["cached_row_count"] == 6
    assert report["missing_row_count"] == 0
    assert report["warning_only_row_count"] == 6
    assert report["normal_backtests_deferred"] is True
    assert report["exploratory_only_command_count"] == 12
    assert report["normal_backtest_executed"] is False
    assert report["exploratory_backtest_executed"] is False
    assert report["parameter_values_changed"] is False
    assert report["optimization_performed"] is False
    assert all(command["run_now"] is False for command in report["exploratory_only_command_plan"])
    assert all("state/" not in command["output_path"] for command in report["exploratory_only_command_plan"])


def test_preflight_architecture_keeps_live_routes_ack_gated_or_blocked() -> None:
    report = build_24h_preflight_architecture(
        coverage_report=_coverage(),
        quality_report=_quality(),
        readiness_report={"status": "readiness_ready"},
        as_of="2026-06-01T00:00:00Z",
    )

    assert report["scope_routes"]["btc_usdc_only"]["status"] == "ack_gated"
    assert report["scope_routes"]["all_ticker_24h"]["status"] == "blocked"
    assert report["no_live_action"] is True
    assert report["contains_live_instructions"] is False
    assert report["parameter_change_allowed"] is False


def test_master_packet_blocks_all_ticker_and_keeps_learning_disabled() -> None:
    warning = build_dataset_quality_warning_diagnostic(quality_report=_quality(), as_of="2026-06-01T00:00:00Z")
    exploratory = build_exploratory_backtest_readiness(
        coverage_report=_coverage(),
        quality_report=_quality(),
        as_of="2026-06-01T00:00:00Z",
    )
    preflight = build_24h_preflight_architecture(
        coverage_report=_coverage(),
        quality_report=_quality(),
        readiness_report={"status": "readiness_ready"},
        as_of="2026-06-01T00:00:00Z",
    )
    report = build_24h_readiness_master_v10(
        warning_diagnostic=warning,
        exploratory_readiness=exploratory,
        preflight_architecture=preflight,
        as_of="2026-06-01T00:00:00Z",
    )

    assert report["coverage_status"] == "complete_required_cached_rows"
    assert report["dataset_quality_status"] == "warning_only"
    assert report["normal_backtest_status"] == "deferred"
    assert report["all_ticker_24h_status"] == "blocked"
    assert report["learning_to_execution_enabled"] is False
    assert report["parameter_review_approved"] is False
