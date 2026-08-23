from __future__ import annotations

from bot.phase_d6_remaining_work_planner import build_remaining_workflow_execution_plan, build_remaining_workflow_todo_overview


def _safe(report):
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["parameter_review_approved"] is False
    assert report["contains_rankings"] is False
    assert report["learning_to_execution_enabled"] is False


def test_remaining_work_planner_groups_todos_and_selects_route_c():
    overview = build_remaining_workflow_todo_overview(
        dataset_plan={"content": {"missing_row_count": 53}},
        readiness_matrix={"content": {"summary": {"baseline_possible_tickers": ["BTC-USDC"], "blocked_tickers": ["BTC-USDC", "ETH-USDC"]}}},
        scaffold={},
        guardrails={},
        workflow_equivalence={},
        readiness_v3={"content": {"routes": {"btc_usdc_only_24h": {"status": "warn_ack_required"}, "all_ticker_24h": {"status": "blocked"}}}},
    )
    execution = build_remaining_workflow_execution_plan(overview=overview)
    assert {row["group"] for row in overview["todo_items"]} >= {"P0 safety/blockers", "P1 data coverage", "P4 backlearning/parameter-review readiness"}
    assert overview["summary"]["missing_dataset_rows"] == 53
    assert execution["chosen_route"] == "C_overview_plus_packages"
    _safe(overview)
    _safe(execution)
