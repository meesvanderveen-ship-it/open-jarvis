from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bot.phase_safe_regression_harness import (
    build_safe_regression_harness,
    render_safe_regression_harness_markdown,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_state(root: Path, *, orders: dict | None = None) -> tuple[str, str]:
    open_orders = root / "state" / "open_orders.json"
    positions = root / "state" / "positions.json"
    _write_json(open_orders, {"orders": orders or {}})
    _write_json(positions, {"BTC-USDC": {"ticker": "BTC-USDC", "status": "closed", "position_size_base": "0"}})
    return _sha(open_orders), _sha(positions)


def _write_required_reports(root: Path, *, hygiene_status: str = "OK") -> None:
    reports = root / "reports" / "d6"
    _write_json(
        reports / "state-hygiene-cleanup-preview-20260609.json",
        {
            "phase": "state_hygiene_cleanup_preview_v1",
            "status": hygiene_status,
            "cleanup_preview_count": 0,
            "safe_cleanup_preview_count": 0,
            "apply_now": False,
            "state_write_performed": False,
            "readiness_flags": {
                "master_ready_for_operator_preflight": True,
                "follower_ready_for_paper_lifecycle_test": True,
                "state_hygiene_cleanup_preview_ready": True,
                "state_hygiene_apply_ready": False,
            },
        },
    )
    _write_json(
        reports / "exit-workflow-readiness-report-20260609.json",
        {
            "exit_workflow_readiness_report_ready": True,
            "master_ready_for_operator_preflight": True,
            "master_ready_for_operator_live_start": False,
            "master_live_exit_ready": False,
            "follower_sell_ready": False,
            "lifecycle_parity_ready": False,
            "all_ticker_ready": False,
            "learning_to_execution_ready": False,
            "current_order_state": {"open_orders": 0, "open_d3_exit": 0},
        },
    )
    _write_json(
        reports / "replication-lifecycle-publisher-scaffold-20260609.json",
        {
            "publisher_scaffold_ready": True,
            "http_replication_call_attempted": False,
            "lifecycle_runtime_integrated": False,
        },
    )
    _write_json(
        reports / "replication-lifecycle-golden-payloads-20260609.json",
        {
            "lifecycle_payloads_valid": True,
            "simulator_validation_passed": True,
            "follower_ready_for_paper_lifecycle_test": True,
            "follower_ready_for_live": False,
        },
    )
    _write_json(
        reports / "replication-paper-lifecycle-simulator-20260609.json",
        {
            "simulator_validation_passed": True,
            "live_order_attempted": False,
            "coinbase_call_attempted": False,
            "state_write_performed": False,
            "follower_ready_for_paper_lifecycle_test": True,
        },
    )
    _write_json(
        reports / "operator-24h-live-test-pack-20260609.json",
        {
            "phase": "live_operator_runbook_pack_v1",
            "status": "operator_pack_ready",
            "no_coinbase_call": True,
            "state_write_performed": False,
        },
    )
    _write_json(
        reports / "d5-d6-evidence-expansion-20260609.json",
        {
            "phase": "d5_d6_evidence_expansion_v1",
            "classification": "OK",
            "fee_evidence": {"fee_gap_present": False},
            "readiness_and_governance_flags": {
                "d5_d6_evidence_expansion_ready": True,
                "human_review_ready": True,
                "learning_to_execution_ready": False,
                "parameter_change_allowed": False,
            },
        },
    )
    _write_json(
        reports / "all-ticker-readiness-gate-20260609.json",
        {
            "phase": "all_ticker_readiness_gate_v1",
            "classification": "OK",
            "readiness_flags": {
                "btc_usdc_tiny_scope_ready_for_operator_preflight": True,
                "all_ticker_ready": True,
                "all_ticker_live_allowed_now": False,
            },
            "gate_decision": {
                "tickers_blocked_count": 0,
                "tickers_missing_evidence_count": 0,
            },
        },
    )
    _write_json(
        reports / "follower-receiver-api-audit-20260609.json",
        {
            "phase": "follower_receiver_api_audit_v1",
            "classification": "OK",
            "readiness_flags": {
                "follower_receiver_code_accessible": True,
                "follower_receiver_api_audit_complete": True,
                "follower_ready_for_paper_lifecycle_test": True,
                "follower_buy_ready": False,
                "follower_sell_ready": False,
                "follower_ready_for_live": False,
                "lifecycle_parity_ready": False,
            },
            "follower_code_discovery": {"receiver_code_found": True},
            "endpoint_audit": {
                "decision_endpoint_status": "present",
                "lifecycle_endpoint_status": "present",
            },
        },
    )
    _write_json(
        reports / "main-workflow-parity-report-20260609.json",
        {
            "phase": "main_workflow_parity_report_v1",
            "gate_decision": {
                "main_workflow_parity_report_ready": True,
                "old_multi_ticker_decision_workflow_seen": "partial",
                "all_ticker_lifecycle_parity_ready": False,
                "all_ticker_live_allowed_now": False,
                "btc_usdc_tiny_scope_ready_for_operator_preflight": True,
            },
        },
    )
    _write_json(
        reports / "multi-ticker-paper-lifecycle-replay-20260609.json",
        {
            "phase": "multi_ticker_paper_lifecycle_replay_v1",
            "classification": "OK",
            "gate_decision": {
                "multi_ticker_paper_lifecycle_replay_ready": True,
                "all_ticker_lifecycle_parity_ready": False,
                "all_ticker_live_allowed_now": False,
                "tickers_replay_ready_count": 3,
                "tickers_replay_partial_count": 0,
                "tickers_blocked_count": 0,
            },
        },
    )
    _write_json(
        reports / "per-ticker-product-rule-evidence-cache-20260609.json",
        {
            "phase": "per_ticker_product_rule_evidence_cache_v1",
            "classification": "OK",
            "gate_decision": {
                "per_ticker_product_rule_evidence_cache_ready": True,
                "all_ticker_product_rule_evidence_ready": True,
                "all_ticker_lifecycle_parity_ready": False,
                "all_ticker_live_allowed_now": False,
                "tickers_ready_count": 3,
                "tickers_partial_count": 0,
                "tickers_missing_count": 0,
            },
        },
    )
    _write_json(
        reports / "d6-backlearning-parameter-evidence-plan-20260609.json",
        {
            "phase": "d6_backlearning_parameter_evidence_plan_v1",
            "classification": "OK",
            "governance_flags": {
                "d6_backlearning_parameter_evidence_plan_ready": True,
                "human_review_ready": True,
                "parameter_review_candidate": False,
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
            },
            "evidence_summary": {
                "evidence_quality_classification": "sufficient_for_human_review_only",
            },
        },
    )
    _write_json(
        reports / "d6-human-review-decision-pack-20260609.json",
        {
            "phase": "d6_human_review_decision_pack_v1",
            "classification": "OK",
            "governance_flags": {
                "d6_human_review_decision_pack_ready": True,
                "human_review_ready": True,
                "parameter_review_candidate": False,
                "parameter_values_proposed": False,
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
            },
            "evidence_source_summary": {
                "evidence_quality_overview": "complete_for_human_review_only",
            },
        },
    )
    _write_json(
        reports / "product-rule-fixture-evidence-20260609.json",
        {
            "phase": "product_rule_fixture_evidence_v1",
            "classification": "OK",
            "universe_summary": {
                "fixture_completion_ready": True,
                "fixture_evidence_ticker_count": 2,
                "live_readonly_cached_ticker_count": 1,
                "missing_evidence_ticker_count": 0,
                "paper_replay_usable_ticker_count": 3,
                "all_ticker_live_allowed_now": False,
            },
        },
    )
    _write_json(
        reports / "d6-acceptance-policy-20260609.json",
        {
            "phase": "d6_acceptance_policy_v1",
            "classification": "OK",
            "governance_flags": {
                "d6_acceptance_policy_ready": True,
                "parameter_review_candidate": False,
                "parameter_values_proposed": False,
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
            },
        },
    )
    _write_json(
        reports / "d6-backlearning-label-export-pack-20260609.json",
        {
            "phase": "d6_backlearning_label_export_pack_v1",
            "classification": "OK",
            "label_counts": {
                "ticker_label_count": 3,
                "lifecycle_label_count": 18,
                "export_record_count": 25,
            },
            "governance_flags": {
                "d6_backlearning_label_export_pack_ready": True,
                "learning_to_execution_ready": False,
            },
        },
    )
    _write_json(
        reports / "roadmap-readiness-decision-map-20260609.json",
        {
            "phase": "roadmap_readiness_decision_map_v1",
            "classification": "OK",
            "route_count": 17,
            "blocked_route_count": 13,
            "ready_route_count": 4,
            "governance_flags": {
                "roadmap_readiness_decision_map_ready": True,
                "d6_shadow_learning_report_ready": True,
                "operator_24h_prerun_build_checklist_ready": True,
                "unresolved_blocker_ledger_ready": True,
                "remaining_locally_buildable_item_count": 0,
                "parameter_review_candidate": False,
                "learning_to_execution_ready": False,
            },
        },
    )
    _write_json(
        reports / "d6-shadow-learning-report-20260609.json",
        {
            "phase": "d6_shadow_learning_report_v1",
            "classification": "OK",
            "governance_flags": {
                "d6_shadow_learning_report_ready": True,
                "report_only_shadow_learning_ready": True,
                "execution_bridge_created": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
            },
        },
    )
    _write_json(
        reports / "operator-24h-prerun-build-checklist-20260609.json",
        {
            "phase": "operator_24h_prerun_build_checklist_v1",
            "classification": "OK",
            "status": "build_complete_for_operator_live_start_review",
            "governance_flags": {
                "operator_24h_prerun_build_checklist_ready": True,
                "build_complete_for_operator_live_start_review": True,
                "live_start_authorized": False,
                "operator_manual_start_required": True,
            },
        },
    )
    _write_json(
        reports / "unresolved-blocker-ledger-20260609.json",
        {
            "phase": "unresolved_blocker_ledger_v1",
            "classification": "OK",
            "governance_flags": {
                "unresolved_blocker_ledger_ready": True,
                "remaining_locally_buildable_item_count": 0,
                "all_remaining_items_are_ack_live_or_external_dependent": True,
            },
        },
    )
    _write_json(
        reports / "btc-usdc-24h-live-start-decision-pack-20260609.json",
        {
            "phase": "btc_usdc_24h_live_start_decision_pack_v1",
            "classification": "OK",
            "decision_status": "ready_for_operator_fresh_preflight",
            "governance_flags": {
                "btc_usdc_24h_live_start_decision_pack_ready": True,
                "ready_for_operator_fresh_preflight": True,
                "live_start_authorized": False,
                "operator_manual_start_required": True,
                "codex_must_not_start_live_test": True,
            },
        },
    )
    _write_json(
        reports / "all-ticker-24h-workflow-readiness-pack-20260609.json",
        {
            "phase": "all_ticker_24h_workflow_readiness_pack_v1",
            "classification": "OK",
            "gate_decision": {
                "all_ticker_24h_workflow_readiness_pack_ready": True,
                "all_ticker_workflow_built_locally": True,
                "all_ticker_ready_for_operator_fresh_preflight": False,
                "all_ticker_live_authorized": False,
                "live_start_authorized": False,
                "btc_usdc_ready_for_operator_fresh_preflight": True,
                "non_btc_tickers_ready_for_operator_fresh_preflight": False,
            },
        },
    )
    _write_json(
        reports / "all-ticker-operator-preflight-command-pack-20260609.json",
        {
            "phase": "all_ticker_operator_preflight_command_pack_v1",
            "classification": "OK",
            "governance_flags": {
                "all_ticker_operator_preflight_command_pack_ready": True,
                "all_commands_operator_only": True,
                "all_ticker_live_authorized": False,
                "live_start_authorized": False,
            },
        },
    )
    _write_json(
        reports / "all-ticker-live-scope-guard-20260609.json",
        {
            "phase": "all_ticker_live_scope_guard_v1",
            "classification": "OK",
            "stop_reasons": [],
            "governance_flags": {
                "all_ticker_live_scope_guard_ready": True,
                "all_ticker_live_authorized": False,
                "live_start_authorized": False,
            },
        },
    )
    _write_json(
        reports / "all-ticker-live-readonly-preflight-20260609.json",
        {
            "phase": "all_ticker_live_readonly_preflight_v1",
            "classification": "WATCH",
            "status": "not_run",
            "gate_decision": {
                "all_ticker_live_readonly_preflight_tool_ready": True,
                "all_ticker_live_readonly_preflight_attempted": False,
                "all_ticker_live_readonly_preflight_passed": False,
                "all_ticker_ready_for_operator_fresh_preflight": False,
                "all_ticker_live_authorized": False,
            },
        },
    )
    _write_json(
        reports / "shadow-parameter-approximation-pack-20260609.json",
        {
            "phase": "shadow_parameter_approximation_pack_v1",
            "classification": "WATCH",
            "governance_flags": {
                "shadow_parameter_approximation_pack_ready": True,
                "parameter_values_approved": False,
                "parameter_change_allowed": False,
                "safe_to_mutate_parameters_now": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
            },
        },
    )
    _write_json(
        reports / "controlled-learning-governance-20260609.json",
        {
            "phase": "controlled_learning_governance_v1",
            "classification": "OK",
            "governance_flags": {
                "controlled_learning_governance_ready": True,
                "current_max_allowed_learning_stage": "acceptance_policy_ready",
                "parameter_proposal_candidate": False,
                "parameter_values_proposed": False,
                "parameter_change_allowed": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
            },
        },
    )


def _audit(status: str = "ok_observe_only") -> dict:
    return {
        "overall_status": status,
        "warnings": [] if status == "ok_observe_only" else ["review_required"],
        "order_store": {"total_open_orders": 0, "open_d3_exit_orders": 0, "ready": status == "ok_observe_only"},
    }


def _build(root: Path, *, audit_status: str = "ok_observe_only", expected_hashes: tuple[str, str] | None = None):
    open_hash, pos_hash = expected_hashes or (_sha(root / "state" / "open_orders.json"), _sha(root / "state" / "positions.json"))
    return build_safe_regression_harness(
        root=root,
        expected_open_orders_hash=open_hash,
        expected_positions_hash=pos_hash,
        function_audit_report=_audit(audit_status),
    )


def _passing_runner(command: list[str], cwd: Path) -> dict:
    return {"returncode": 0, "summary": f"passed {' '.join(command)}"}


def test_all_local_checks_clean_is_ok(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)

    assert report["classification"] == "OK"
    assert report["local_safe_regression_passed"] is True
    assert report["open_order_summary"]["open_orders"] == 0
    assert report["open_order_summary"]["open_d3_exit"] == 0
    assert report["function_preservation_audit"]["overall_status"] == "ok_observe_only"
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["selected_tests"]["selected_tests_enabled"] is False


def test_open_order_present_is_stop_now(tmp_path: Path):
    _write_state(
        tmp_path,
        orders={
            "order-1": {
                "client_order_id": "order-1",
                "ticker": "BTC-USDC",
                "side": "BUY",
                "status": "submitted",
                "remaining_quote": "1",
            }
        },
    )
    _write_required_reports(tmp_path)

    report = _build(tmp_path)

    assert report["classification"] == "STOP_NOW"
    assert "open_orders_present" in report["stop_reasons"]


def test_open_d3_exit_present_is_stop_now(tmp_path: Path):
    _write_state(
        tmp_path,
        orders={
            "d3-1": {
                "client_order_id": "phased3-BTCUSDC-TP1-test",
                "ticker": "BTC-USDC",
                "side": "SELL",
                "phase": "D3_controlled_live_reduce_only_exits",
                "status": "open",
                "remaining_size": "0.0001",
            }
        },
    )
    _write_required_reports(tmp_path)

    report = _build(tmp_path)

    assert report["classification"] == "STOP_NOW"
    assert "open_d3_exit_present" in report["stop_reasons"]


def test_function_audit_fail_is_stop_now(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path, audit_status="review_required")

    assert report["classification"] == "STOP_NOW"
    assert "function_audit_not_ok_observe_only" in report["stop_reasons"]


def test_state_hash_drift_is_watch(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = build_safe_regression_harness(
        root=tmp_path,
        expected_open_orders_hash="expected-old-open",
        expected_positions_hash="expected-old-pos",
        function_audit_report=_audit(),
    )

    assert report["classification"] == "WATCH"
    assert "state_hash_drift_detected" in report["watch_reasons"]
    assert report["local_safe_regression_passed"] is True


def test_missing_optional_report_is_watch_not_crash(tmp_path: Path):
    _write_state(tmp_path)

    report = _build(tmp_path)

    assert report["classification"] == "WATCH"
    assert any(reason.startswith("optional_report_missing:") for reason in report["watch_reasons"])


def test_false_live_and_follower_flags_are_recorded_but_not_stop(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)

    assert report["classification"] == "OK"
    flags = report["readiness_flags"]
    assert flags["master_live_exit_ready"] is False
    assert flags["master_ready_for_operator_live_start"] is False
    assert flags["follower_ready_for_live"] is False
    assert flags["follower_sell_ready"] is False
    assert report["stop_reasons"] == []


def test_output_contains_full_readiness_flags(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    flags = report["readiness_flags"]

    for key in (
        "local_safe_regression_passed",
        "master_ready_for_operator_preflight",
        "master_ready_for_operator_live_start",
        "master_live_exit_ready",
        "follower_receiver_code_accessible",
        "follower_receiver_api_audit_complete",
        "follower_ready_for_paper_lifecycle_test",
        "follower_buy_ready",
        "follower_ready_for_live",
        "follower_sell_ready",
        "lifecycle_parity_ready",
        "all_ticker_ready",
        "learning_to_execution_ready",
        "state_hygiene_cleanup_preview_ready",
        "state_hygiene_apply_ready",
    ):
        assert key in flags
    assert "local_safe_regression_passed" in render_safe_regression_harness_markdown(report)


def test_harness_includes_all_ticker_readiness_gate_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["all_ticker_readiness_gate"]

    assert ref["available"] is True
    assert ref["summary"]["all_ticker_ready"] is True
    assert ref["summary"]["all_ticker_live_allowed_now"] is False


def test_harness_includes_follower_receiver_api_audit_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["follower_receiver_api_audit"]

    assert ref["available"] is True
    assert ref["summary"]["follower_receiver_code_accessible"] is True
    assert ref["summary"]["follower_receiver_api_audit_complete"] is True
    assert report["readiness_flags"]["follower_receiver_api_audit_complete"] is True


def test_harness_includes_main_workflow_parity_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["main_workflow_parity_report"]

    assert ref["available"] is True
    assert ref["summary"]["main_workflow_parity_report_ready"] is True
    assert ref["summary"]["all_ticker_live_allowed_now"] is False


def test_harness_includes_multi_ticker_paper_lifecycle_replay_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["multi_ticker_paper_lifecycle_replay"]

    assert ref["available"] is True
    assert ref["summary"]["multi_ticker_paper_lifecycle_replay_ready"] is True
    assert ref["summary"]["all_ticker_live_allowed_now"] is False


def test_harness_includes_per_ticker_product_rule_evidence_cache_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["per_ticker_product_rule_evidence_cache"]

    assert ref["available"] is True
    assert ref["summary"]["per_ticker_product_rule_evidence_cache_ready"] is True
    assert ref["summary"]["all_ticker_live_allowed_now"] is False


def test_harness_includes_d6_backlearning_parameter_evidence_plan_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["d6_backlearning_parameter_evidence_plan"]

    assert ref["available"] is True
    assert ref["summary"]["d6_backlearning_parameter_evidence_plan_ready"] is True
    assert ref["summary"]["parameter_change_allowed"] is False
    assert ref["summary"]["learning_to_execution_ready"] is False


def test_harness_includes_d6_human_review_decision_pack_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["d6_human_review_decision_pack"]

    assert ref["available"] is True
    assert ref["summary"]["d6_human_review_decision_pack_ready"] is True
    assert ref["summary"]["parameter_values_proposed"] is False
    assert ref["summary"]["parameter_change_allowed"] is False
    assert report["readiness_flags"]["d6_human_review_decision_pack_ready"] is True


def test_harness_includes_product_rule_fixture_evidence_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["product_rule_fixture_evidence"]

    assert ref["available"] is True
    assert ref["summary"]["product_rule_fixture_evidence_ready"] is True
    assert ref["summary"]["fixture_evidence_ticker_count"] == 2
    assert ref["summary"]["all_ticker_live_allowed_now"] is False
    assert report["readiness_flags"]["product_rule_fixture_evidence_ready"] is True


def test_harness_includes_d6_acceptance_policy_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["d6_acceptance_policy"]

    assert ref["available"] is True
    assert ref["summary"]["d6_acceptance_policy_ready"] is True
    assert ref["summary"]["parameter_review_candidate"] is False
    assert report["readiness_flags"]["d6_acceptance_policy_ready"] is True


def test_harness_includes_d6_backlearning_label_export_pack_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["d6_backlearning_label_export_pack"]

    assert ref["available"] is True
    assert ref["summary"]["d6_backlearning_label_export_pack_ready"] is True
    assert ref["summary"]["export_record_count"] == 25
    assert report["readiness_flags"]["d6_backlearning_label_export_pack_ready"] is True


def test_harness_includes_roadmap_readiness_decision_map_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["roadmap_readiness_decision_map"]

    assert ref["available"] is True
    assert ref["summary"]["roadmap_readiness_decision_map_ready"] is True
    assert ref["summary"]["route_count"] == 17
    assert report["readiness_flags"]["roadmap_readiness_decision_map_ready"] is True


def test_harness_includes_controlled_learning_governance_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["controlled_learning_governance"]

    assert ref["available"] is True
    assert ref["summary"]["controlled_learning_governance_ready"] is True
    assert ref["summary"]["current_max_allowed_learning_stage"] == "acceptance_policy_ready"
    assert ref["summary"]["parameter_proposal_candidate"] is False
    assert report["readiness_flags"]["controlled_learning_governance_ready"] is True


def test_harness_includes_shadow_learning_checklist_and_ledger_references(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)

    shadow = report["report_references"]["d6_shadow_learning_report"]
    checklist = report["report_references"]["operator_24h_prerun_build_checklist"]
    ledger = report["report_references"]["unresolved_blocker_ledger"]
    flags = report["readiness_flags"]

    assert shadow["summary"]["d6_shadow_learning_report_ready"] is True
    assert shadow["summary"]["execution_bridge_created"] is False
    assert checklist["summary"]["build_complete_for_operator_live_start_review"] is True
    assert checklist["summary"]["live_start_authorized"] is False
    assert ledger["summary"]["remaining_locally_buildable_item_count"] == 0
    assert flags["d6_shadow_learning_report_ready"] is True
    assert flags["operator_24h_prerun_build_checklist_ready"] is True
    assert flags["unresolved_blocker_ledger_ready"] is True


def test_harness_includes_btc_usdc_live_start_decision_pack_reference(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    ref = report["report_references"]["btc_usdc_24h_live_start_decision_pack"]

    assert ref["available"] is True
    assert ref["summary"]["btc_usdc_24h_live_start_decision_pack_ready"] is True
    assert ref["summary"]["ready_for_operator_fresh_preflight"] is True
    assert ref["summary"]["live_start_authorized"] is False
    assert report["readiness_flags"]["btc_usdc_24h_live_start_decision_pack_ready"] is True


def test_harness_includes_all_ticker_24h_workflow_reports(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    refs = report["report_references"]
    flags = report["readiness_flags"]

    assert refs["all_ticker_24h_workflow_readiness_pack"]["available"] is True
    assert refs["all_ticker_24h_workflow_readiness_pack"]["summary"][
        "all_ticker_24h_workflow_readiness_pack_ready"
    ] is True
    assert refs["all_ticker_operator_preflight_command_pack"]["summary"][
        "all_ticker_operator_preflight_command_pack_ready"
    ] is True
    assert refs["all_ticker_live_scope_guard"]["summary"]["all_ticker_live_scope_guard_ready"] is True
    assert flags["all_ticker_24h_workflow_readiness_pack_ready"] is True
    assert flags["all_ticker_operator_preflight_command_pack_ready"] is True
    assert flags["all_ticker_live_scope_guard_ready"] is True
    assert flags["all_ticker_workflow_built_locally"] is True
    assert flags["all_ticker_ready_for_operator_fresh_preflight"] is False
    assert flags["all_ticker_live_authorized"] is False


def test_harness_includes_live_readonly_preflight_and_shadow_params(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = _build(tmp_path)
    refs = report["report_references"]
    flags = report["readiness_flags"]

    assert refs["all_ticker_live_readonly_preflight"]["summary"][
        "all_ticker_live_readonly_preflight_tool_ready"
    ] is True
    assert refs["all_ticker_live_readonly_preflight"]["summary"][
        "all_ticker_live_readonly_preflight_attempted"
    ] is False
    assert refs["shadow_parameter_approximation_pack"]["summary"][
        "shadow_parameter_approximation_pack_ready"
    ] is True
    assert flags["all_ticker_live_readonly_preflight_tool_ready"] is True
    assert flags["all_ticker_live_readonly_preflight_passed"] is False
    assert flags["shadow_parameter_approximation_pack_ready"] is True
    assert flags["safe_to_mutate_parameters_now"] is False


def test_default_harness_does_not_run_selected_tests(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = build_safe_regression_harness(
        root=tmp_path,
        expected_open_orders_hash=_sha(tmp_path / "state" / "open_orders.json"),
        expected_positions_hash=_sha(tmp_path / "state" / "positions.json"),
        function_audit_report=_audit(),
        selected_test_runner=lambda command, cwd: (_ for _ in ()).throw(AssertionError("runner called")),
    )

    assert report["selected_tests"]["selected_tests_enabled"] is False
    assert report["selected_tests"]["selected_tests_run_count"] == 0


def test_include_selected_tests_runs_only_allowlisted_tests(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)
    test_path = tmp_path / "tests" / "test_safe_regression_harness.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_ok(): pass\n", encoding="utf-8")
    seen: list[list[str]] = []

    def runner(command: list[str], cwd: Path) -> dict:
        seen.append(command)
        return {"returncode": 0, "summary": "passed"}

    report = build_safe_regression_harness(
        root=tmp_path,
        expected_open_orders_hash=_sha(tmp_path / "state" / "open_orders.json"),
        expected_positions_hash=_sha(tmp_path / "state" / "positions.json"),
        function_audit_report=_audit(),
        include_selected_tests=True,
        selected_test_runner=runner,
        selected_test_specs=[{"path": "tests/test_safe_regression_harness.py", "required": True}],
    )

    assert report["classification"] == "OK"
    assert report["selected_tests"]["selected_tests_classification"] == "OK"
    assert seen == [[seen[0][0], "-m", "pytest", "-q", "tests/test_safe_regression_harness.py"]]


def test_optional_missing_selected_test_is_watch_not_stop(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    report = build_safe_regression_harness(
        root=tmp_path,
        expected_open_orders_hash=_sha(tmp_path / "state" / "open_orders.json"),
        expected_positions_hash=_sha(tmp_path / "state" / "positions.json"),
        function_audit_report=_audit(),
        include_selected_tests=True,
        selected_test_runner=_passing_runner,
        selected_test_specs=[{"path": "tests/test_btc_usdc_24h_monitor.py", "required": False}],
    )

    assert report["classification"] == "WATCH"
    assert report["selected_tests"]["selected_tests_classification"] == "WATCH"
    assert report["selected_tests"]["selected_tests_missing_optional_count"] == 1
    assert report["local_safe_regression_passed"] is True


def test_required_selected_test_failure_is_stop_now(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)
    test_path = tmp_path / "tests" / "test_safe_regression_harness.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_fail(): assert False\n", encoding="utf-8")

    report = build_safe_regression_harness(
        root=tmp_path,
        expected_open_orders_hash=_sha(tmp_path / "state" / "open_orders.json"),
        expected_positions_hash=_sha(tmp_path / "state" / "positions.json"),
        function_audit_report=_audit(),
        include_selected_tests=True,
        selected_test_runner=lambda command, cwd: {"returncode": 1, "summary": "failed"},
        selected_test_specs=[{"path": "tests/test_safe_regression_harness.py", "required": True}],
    )

    assert report["classification"] == "STOP_NOW"
    assert report["local_safe_regression_passed"] is False
    assert "selected_tests_required_failure" in report["stop_reasons"]


def test_forbidden_selected_test_command_is_rejected(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)

    try:
        build_safe_regression_harness(
            root=tmp_path,
            expected_open_orders_hash=_sha(tmp_path / "state" / "open_orders.json"),
            expected_positions_hash=_sha(tmp_path / "state" / "positions.json"),
            function_audit_report=_audit(),
            include_selected_tests=True,
            selected_test_runner=_passing_runner,
            selected_test_specs=[{"path": "tests/test_safe_regression_harness.py;rm -rf /", "required": True}],
        )
    except ValueError as exc:
        assert "selected_test_not_allowlisted" in str(exc)
    else:
        raise AssertionError("forbidden selected test path was not rejected")


def test_selected_test_output_contains_summaries_and_no_action_flags(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)
    test_path = tmp_path / "tests" / "test_safe_regression_harness.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_ok(): pass\n", encoding="utf-8")

    report = build_safe_regression_harness(
        root=tmp_path,
        expected_open_orders_hash=_sha(tmp_path / "state" / "open_orders.json"),
        expected_positions_hash=_sha(tmp_path / "state" / "positions.json"),
        function_audit_report=_audit(),
        include_selected_tests=True,
        selected_test_runner=lambda command, cwd: {"returncode": 0, "summary": "1 passed"},
        selected_test_specs=[{"path": "tests/test_safe_regression_harness.py", "required": True}],
    )
    markdown = render_safe_regression_harness_markdown(report)

    assert "Selected Tests" in markdown
    assert report["no_coinbase_call_confirmed"] is True
    assert report["no_http_call_confirmed"] is True
    assert report["no_state_write_confirmed"] is True


def test_no_state_writes(tmp_path: Path):
    _write_state(tmp_path)
    _write_required_reports(tmp_path)
    orders_before = (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8")
    positions_before = (tmp_path / "state" / "positions.json").read_text(encoding="utf-8")

    report = _build(tmp_path)

    assert report["state_write_performed"] is False
    assert (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8") == orders_before
    assert (tmp_path / "state" / "positions.json").read_text(encoding="utf-8") == positions_before
