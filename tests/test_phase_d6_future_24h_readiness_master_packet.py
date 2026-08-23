from __future__ import annotations

from bot.phase_d6_remaining_work_planner import build_future_24h_readiness_master_packet


def test_master_packet_separates_btc_route_from_all_ticker_blocked_route():
    master = build_future_24h_readiness_master_packet(
        overview={"summary": {"missing_dataset_rows": 53}},
        execution_plan={"chosen_route": "C_overview_plus_packages", "next_non_live_step": "review"},
        fetch_package={"missing_row_count": 53, "required_ack": "ACK"},
        backtest_package={"rows": [1, 2], "blocked_until_data_exists": True},
        backlearning_package={"explicit_blockers": {"parameter_review_approved": False}},
        checklist={"summary": {"blocked_count": 18}},
        readiness_v3={"content": {"routes": {"btc_usdc_only_24h": {"status": "warn_ack_required"}, "all_ticker_24h": {"status": "blocked"}}}},
        state_hashes={"state/open_orders.json": "x"},
    )
    assert master["btc_usdc_only_route"]["status"] == "warn_ack_required"
    assert master["all_ticker_route"]["status"] == "blocked"
    assert master["fetch_package_summary"]["missing_row_count"] == 53
    assert master["learning_to_execution_enabled"] is False
    assert master["parameter_review_approved"] is False
