from bot.phase_d6_non_live_readiness_continuation import build_master_readiness_refresh_v2


def test_master_readiness_refresh_v2_preserves_no_go_boundaries() -> None:
    report = build_master_readiness_refresh_v2(
        prefetch_validation={"status": "prefetch_validation_pass"},
        evidence_aggregator={"status": "blocked"},
        gap_tracker={"summary": {"blocked_count": 18}},
        ack_packet={"status": "ready"},
        remaining_overview={"content": {"todo_items": [{"group": "P0", "item": "keep gates"}]}},
        state_hashes={"state/open_orders.json": "abc"},
    )

    assert report["status"] == "master_readiness_refresh_v2_ready"
    assert report["newest_blockers"]["all_ticker_live_blocked"] is True
    assert report["current_safety"]["live_action_authorized"] is False
    assert report["state_write_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert "no_learning_to_execution" in report["no_go_boundaries"]
