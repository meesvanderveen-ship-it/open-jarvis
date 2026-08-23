from __future__ import annotations

import json
from pathlib import Path

from bot.phase_roadmap_readiness_decision_map import (
    build_roadmap_readiness_decision_map_report,
    render_roadmap_readiness_decision_map_markdown,
)


def _write_sources(root: Path) -> None:
    d6 = root / "reports" / "d6"
    d6.mkdir(parents=True)
    (d6 / "safe-regression-harness-20260609.json").write_text(
        json.dumps({"readiness_flags": {"local_safe_regression_passed": True}}),
        encoding="utf-8",
    )
    (d6 / "multi-ticker-paper-lifecycle-replay-20260609.json").write_text(
        json.dumps(
            {
                "gate_decision": {
                    "fixture_evidence_consumed": True,
                    "multi_ticker_paper_lifecycle_replay_ready": True,
                    "paper_lifecycle_replay_ready_count": 18,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "d6-acceptance-policy-20260609.json").write_text(
        json.dumps({"governance_flags": {"d6_acceptance_policy_ready": True}}),
        encoding="utf-8",
    )
    (d6 / "d6-backlearning-label-export-pack-20260609.json").write_text(
        json.dumps({"governance_flags": {"d6_backlearning_label_export_pack_ready": True}}),
        encoding="utf-8",
    )
    (d6 / "controlled-learning-governance-20260609.json").write_text(
        json.dumps(
            {
                "governance_flags": {
                    "controlled_learning_governance_ready": True,
                    "current_max_allowed_learning_stage": "acceptance_policy_ready",
                    "parameter_proposal_candidate": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "d6-shadow-learning-report-20260609.json").write_text(
        json.dumps(
            {
                "governance_flags": {
                    "d6_shadow_learning_report_ready": True,
                    "report_only_shadow_learning_ready": True,
                    "execution_bridge_created": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "operator-24h-prerun-build-checklist-20260609.json").write_text(
        json.dumps(
            {
                "governance_flags": {
                    "operator_24h_prerun_build_checklist_ready": True,
                    "build_complete_for_operator_live_start_review": True,
                    "live_start_authorized": False,
                    "operator_manual_start_required": True,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "unresolved-blocker-ledger-20260609.json").write_text(
        json.dumps(
            {
                "governance_flags": {
                    "unresolved_blocker_ledger_ready": True,
                    "remaining_locally_buildable_item_count": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "all-ticker-24h-workflow-readiness-pack-20260609.json").write_text(
        json.dumps(
            {
                "gate_decision": {
                    "all_ticker_24h_workflow_readiness_pack_ready": True,
                    "all_ticker_workflow_built_locally": True,
                    "all_ticker_ready_for_operator_fresh_preflight": False,
                    "all_ticker_live_authorized": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "all-ticker-operator-preflight-command-pack-20260609.json").write_text(
        json.dumps(
            {
                "governance_flags": {
                    "all_ticker_operator_preflight_command_pack_ready": True,
                    "all_ticker_live_authorized": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "all-ticker-live-scope-guard-20260609.json").write_text(
        json.dumps(
            {
                "governance_flags": {
                    "all_ticker_live_scope_guard_ready": True,
                    "all_ticker_live_authorized": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "all-ticker-live-readonly-preflight-20260609.json").write_text(
        json.dumps(
            {
                "gate_decision": {
                    "all_ticker_live_readonly_preflight_tool_ready": True,
                    "all_ticker_live_readonly_preflight_attempted": False,
                    "all_ticker_live_readonly_preflight_passed": False,
                    "all_ticker_ready_for_operator_fresh_preflight": False,
                    "all_ticker_live_authorized": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "shadow-parameter-approximation-pack-20260609.json").write_text(
        json.dumps(
            {
                "governance_flags": {
                    "shadow_parameter_approximation_pack_ready": True,
                    "parameter_values_approved": False,
                    "parameter_change_allowed": False,
                    "safe_to_mutate_parameters_now": False,
                }
            }
        ),
        encoding="utf-8",
    )
    (d6 / "follower-receiver-api-audit-20260609.json").write_text(
        json.dumps({"readiness_flags": {"follower_receiver_code_accessible": False, "follower_ready_for_live": False}}),
        encoding="utf-8",
    )
    (d6 / "exit-workflow-readiness-report-20260609.json").write_text(
        json.dumps({"master_live_exit_ready": False}),
        encoding="utf-8",
    )


def test_every_route_has_blockers_and_allowed_next_step(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_roadmap_readiness_decision_map_report(root=tmp_path)

    assert report["route_count"] >= 12
    for route in report["routes"]:
        assert route["blockers"]
        assert route["allowed_next_step"]
        assert route["current_decision"] in {"allowed", "allowed_report_only", "blocked", "blocked_by_ACK", "out_of_scope"}
        assert route["live_trading_authorized"] is False


def test_live_start_route_requires_ack(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_roadmap_readiness_decision_map_report(root=tmp_path)
    route = {row["route"]: row for row in report["routes"]}["BTC-USDC 24h live-start decision"]

    assert route["requires_ACK"] is True
    assert route["blocks_BTC_24h"] is True
    assert "start live trading" in route["forbidden_actions"]


def test_blocked_routes_remain_blocked(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_roadmap_readiness_decision_map_report(root=tmp_path)
    routes = {row["route"]: row for row in report["routes"]}

    assert routes["all-ticker lifecycle parity"]["current_status"] == "local_workflow_built_live_blocked"
    assert routes["all-ticker 24h workflow readiness"]["current_status"] == "built_report_only_live_blocked"
    assert routes["all-ticker 24h workflow readiness"]["current_decision"] == "blocked"
    assert routes["all-ticker live-readonly preflight"]["current_status"] == "tool_ready_not_run"
    assert routes["shadow parameter approximation"]["current_decision"] == "allowed_report_only"
    assert routes["parameter review candidate status"]["current_status"] == "blocked"
    assert routes["live learning governance"]["current_status"] == "blocked"
    assert routes["follower/replication readiness"]["current_status"] == "blocked"
    assert routes["human_review_to_parameter_review_candidate"]["current_decision"] == "blocked"
    assert routes["parameter_review_to_parameter_proposal"]["current_decision"] == "blocked"
    assert routes["execution_bridge_to_live_learning"]["current_decision"] == "blocked"
    assert routes["parameter_change_to_shadow_learning"]["current_decision"] == "allowed_report_only"


def test_learning_boundary_routes_are_present(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_roadmap_readiness_decision_map_report(root=tmp_path)
    route_names = {row["route"] for row in report["routes"]}

    for name in (
        "evidence_to_human_review",
        "human_review_to_parameter_review_candidate",
        "parameter_review_to_parameter_proposal",
        "parameter_proposal_to_parameter_change",
        "parameter_change_to_shadow_learning",
        "shadow_learning_to_execution_bridge",
        "execution_bridge_to_live_learning",
    ):
        assert name in route_names


def test_no_route_authorizes_live_or_parameters(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_roadmap_readiness_decision_map_report(root=tmp_path)

    for route in report["routes"]:
        assert route["live_trading_authorized"] is False
        assert route["parameter_change_allowed"] is False
        assert route["learning_to_execution_ready"] is False
        assert route["current_decision"] != "allowed" or route["route"] != "BTC-USDC 24h live-start decision"


def test_parameter_change_and_live_learning_require_ack_or_remain_blocked(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    routes = {row["route"]: row for row in build_roadmap_readiness_decision_map_report(root=tmp_path)["routes"]}

    assert routes["parameter_proposal_to_parameter_change"]["current_decision"] == "blocked_by_ACK"
    assert routes["parameter_proposal_to_parameter_change"]["requires_ACK"] is True
    assert routes["execution_bridge_to_live_learning"]["current_decision"] == "blocked"
    assert routes["execution_bridge_to_live_learning"]["requires_ACK"] is True


def test_map_consumes_new_build_closure_reports(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_roadmap_readiness_decision_map_report(root=tmp_path)
    flags = report["governance_flags"]
    routes = {row["route"]: row for row in report["routes"]}

    assert flags["d6_shadow_learning_report_ready"] is True
    assert flags["operator_24h_prerun_build_checklist_ready"] is True
    assert flags["unresolved_blocker_ledger_ready"] is True
    assert flags["all_ticker_24h_workflow_readiness_pack_ready"] is True
    assert flags["all_ticker_operator_preflight_command_pack_ready"] is True
    assert flags["all_ticker_live_scope_guard_ready"] is True
    assert flags["all_ticker_workflow_built_locally"] is True
    assert flags["all_ticker_live_authorized"] is False
    assert flags["all_ticker_live_readonly_preflight_tool_ready"] is True
    assert flags["all_ticker_live_readonly_preflight_attempted"] is False
    assert flags["all_ticker_live_readonly_preflight_passed"] is False
    assert flags["shadow_parameter_approximation_pack_ready"] is True
    assert flags["safe_to_mutate_parameters_now"] is False
    assert flags["remaining_locally_buildable_item_count"] == 0
    assert routes["operator 24h pre-run build closure"]["current_decision"] == "allowed_report_only"
    assert routes["unresolved blocker ledger"]["current_decision"] == "allowed_report_only"
    assert routes["BTC-USDC 24h live-start decision"]["current_decision"] == "blocked_by_ACK"


def test_no_external_or_state_side_effect_flags(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    meta = build_roadmap_readiness_decision_map_report(root=tmp_path)["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False


def test_markdown_contains_routes(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    markdown = render_roadmap_readiness_decision_map_markdown(
        build_roadmap_readiness_decision_map_report(root=tmp_path)
    )

    assert "Roadmap Readiness Decision Map" in markdown
    assert "BTC-USDC 24h live-start decision" in markdown
