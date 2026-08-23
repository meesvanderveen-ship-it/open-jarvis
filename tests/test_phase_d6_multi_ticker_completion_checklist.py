from __future__ import annotations

from bot.phase_d6_remaining_work_planner import build_multi_ticker_workflow_completion_checklist


def test_completion_checklist_keeps_all_ticker_route_blocked_when_evidence_missing():
    report = build_multi_ticker_workflow_completion_checklist(
        readiness_matrix={"content": {"rows": [{"ticker": "BTC-USDC", "required_timeframes_missing": ["1H", "4H"], "dataset_quality_present": False, "baseline_backtest_possible": True, "fill_realism_evidence_present": True}]}},
        workflow_equivalence={"content": {"rows": [{"ticker": "BTC-USDC", "open_order_safety_compatibility": True, "lifecycle_evidence": True, "readiness_for_future_controlled_live_pilot": "btc_scope_ack_blocked", "blockers_before_ticker_can_join_24h_live_test": ["missing_candle_coverage_1h_4h_1d"]}]}},
    )
    row = report["rows"][0]
    assert row["candles_1d"] is True
    assert row["candles_1h"] is False
    assert row["readiness_for_24h_inclusion"] == "blocked"
    assert report["summary"]["blocked_count"] == 1
    assert report["no_live_action"] is True
