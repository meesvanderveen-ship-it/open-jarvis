from bot.phase_d6_non_live_readiness_continuation import build_gap_closure_tracker


def test_gap_closure_tracker_separates_btc_from_configured_only_tickers() -> None:
    checklist = {
        "content": {
            "rows": [
                {"ticker": "BTC-USDC", "configured": True, "candles_1d": True, "candles_1h": False, "candles_4h": False, "dataset_quality": False, "cached_baseline": True, "lifecycle_evidence": True, "blockers": ["missing_candle_coverage_1h_4h_1d"]},
                {"ticker": "ETH-USDC", "configured": True, "candles_1d": False, "candles_1h": False, "candles_4h": False, "dataset_quality": False, "cached_baseline": False, "lifecycle_evidence": False, "blockers": ["missing_baseline_backtest_input"]},
            ]
        }
    }
    matrix = {
        "content": {
            "rows": [
                {"ticker": "BTC-USDC", "required_timeframes_missing": ["1H", "4H"]},
                {"ticker": "ETH-USDC", "required_timeframes_missing": ["1H", "4H", "1D"]},
            ]
        }
    }
    workflow = {"content": {"rows": []}}

    report = build_gap_closure_tracker(checklist=checklist, readiness_matrix=matrix, workflow_equivalence=workflow)

    statuses = {row["ticker"]: row["closure_status"] for row in report["rows"]}
    assert statuses["BTC-USDC"] == "data_coverage_partial"
    assert statuses["ETH-USDC"] == "configured_only"
    assert report["summary"]["workflow_equivalent_to_btc_usdc_count"] == 0
