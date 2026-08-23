from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_governance_evidence_bundle import (
    _d3_summary,
    _open_orders_summary,
    _state_hash_summary,
    parse_function_preservation_audit,
)
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_LIVE_TEST_READINESS_PHASE = "D6_live_test_readiness_governance_report_v1"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def _normalize_governance_bundle(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not report:
        return {}
    if isinstance(report.get("content"), dict):
        return dict(report["content"])
    return dict(report)


def _gate(
    *,
    gate_id: str,
    name: str,
    status: str,
    evidence: Dict[str, Any],
    remaining_work: Iterable[str] = (),
    ack_required: bool = False,
    safe_to_bundle_now: Iterable[str] = (),
    must_stay_separate: Iterable[str] = (),
) -> Dict[str, Any]:
    return {
        "gate_id": gate_id,
        "name": name,
        "status": status,
        "evidence": dict(evidence),
        "remaining_work": list(remaining_work),
        "ack_required": bool(ack_required),
        "safe_to_bundle_now": list(safe_to_bundle_now),
        "must_stay_separate": list(must_stay_separate),
    }


def _workstream(
    *,
    key: str,
    status: str,
    remaining_tasks: Iterable[str],
    blockers: Iterable[str],
    safe_to_bundle_tasks: Iterable[str],
    must_stay_separate_tasks: Iterable[str],
    tests_checks: Iterable[str],
    deliverables: Iterable[str],
    ack_required: bool,
) -> Dict[str, Any]:
    return {
        "key": key,
        "status": status,
        "remaining_tasks": list(remaining_tasks),
        "blockers": list(blockers),
        "safe_to_bundle_tasks": list(safe_to_bundle_tasks),
        "must_stay_separate_tasks": list(must_stay_separate_tasks),
        "tests_checks": list(tests_checks),
        "deliverables": list(deliverables),
        "ack_required": bool(ack_required),
    }


def _route_score(
    *,
    route: str,
    value_toward_live_test_readiness: int,
    safety_risk: int,
    testability: int,
    size: int,
    bundling_strength: int,
    loop_reduction_value: int,
    touches_trading_state: bool,
    ack_required: bool,
    decision: str,
) -> Dict[str, Any]:
    return {
        "route": route,
        "value_toward_live_test_readiness": value_toward_live_test_readiness,
        "safety_risk": safety_risk,
        "testability": testability,
        "size": size,
        "bundling_strength": bundling_strength,
        "loop_reduction_value": loop_reduction_value,
        "touches_trading_state": bool(touches_trading_state),
        "ack_required": bool(ack_required),
        "decision": decision,
    }


def _readiness_gates(
    *,
    open_orders: Dict[str, Any],
    function_audit: Dict[str, Any],
    d3: Dict[str, Any],
    state_hashes_match: bool,
    governance_bundle: Dict[str, Any],
    environment_summary: Dict[str, Any],
    regression_summary: Dict[str, Any],
) -> List[Dict[str, Any]]:
    gate0_ok = (
        open_orders.get("open_orders") in (0, "0")
        and function_audit.get("status") == "ok_observe_only"
        and function_audit.get("open_d3_exit") in (0, "0")
        and d3.get("open_d3_exit_count") in (0, "0")
        and d3.get("status") == "d3_no_manageable_open_position"
        and not d3.get("live_order_submitted")
        and not d3.get("live_submission_attempted")
    )
    evidence = dict(governance_bundle.get("historical_evidence_summary") or {})
    environment_bwrap = environment_summary.get("bwrap_on_path")
    regression_status = regression_summary.get("status")
    regression_passed = regression_status == "pass"
    return [
        _gate(
            gate_id="gate_0",
            name="live_lifecycle_parked",
            status="pass" if gate0_ok else "blocked",
            evidence={
                "open_orders": open_orders.get("open_orders"),
                "function_audit_status": function_audit.get("status"),
                "open_d3_exit": d3.get("open_d3_exit_count"),
                "d3_status": d3.get("status"),
                "position_present": d3.get("position_present"),
            },
            remaining_work=[] if gate0_ok else ["produce_live_lifecycle_diagnostic_plan_only"],
            must_stay_separate=["any_live_order_or_coinbase_poll"],
        ),
        _gate(
            gate_id="gate_1",
            name="state_hygiene_understood",
            status="warning",
            evidence={
                "derived_reserved_base_open_exit_orders": d3.get("reserved_base_open_exit_orders"),
                "state_hashes_match": state_hashes_match,
                "known_stale_denormalized_field": "reserved_base_open_exit_orders=0.00006490",
                "known_fee_evidence_gap": "TP_CLOSE lifecycle fee fields are zero while Coinbase evidence showed 0.0288156",
            },
            remaining_work=[
                "design_or_run_preview_only_post_filled_stale_field_cleanup",
                "keep_fee_gap_as_evidence_item_until_exact_repair_ack",
            ],
            safe_to_bundle_now=["preview_only_cleanup_design", "operator_doc_hardening"],
            must_stay_separate=["local_repair_apply", "dust_close_trade", "manual_position_close"],
        ),
        _gate(
            gate_id="gate_2",
            name="regression_readiness",
            status="pass" if regression_passed else "warning",
            evidence={
                "function_audit_status": function_audit.get("status"),
                "governance_bundle_overall_status": governance_bundle.get("overall_status"),
                "readiness_regression_status": regression_status or "not_supplied",
                "readiness_regression_tests_passed": regression_summary.get("tests_passed"),
                "readiness_regression_command": regression_summary.get("command"),
            },
            remaining_work=[
                "keep_d3_d4_d6_readiness_regression_green_before_future_live_test_prompt"
            ]
            if regression_passed
            else [
                "run_d3_d4_safety_regression_before_live_test_prompt",
                "keep_d6_governance_regression_green",
            ],
            safe_to_bundle_now=["report_only_readiness_regression_summary"],
            must_stay_separate=["service_restart", "runtime_config_mutation"],
        ),
        _gate(
            gate_id="gate_3",
            name="research_report_governance",
            status="pass" if governance_bundle.get("overall_status") == "pass" and not evidence.get("blockers") else "warning",
            evidence={
                "governance_bundle_overall_status": governance_bundle.get("overall_status"),
                "evidence_row_count": evidence.get("evidence_row_count"),
                "evidence_category_counts": evidence.get("evidence_category_counts") or {},
            },
            remaining_work=[
                "continue_human_review_only_evidence_improvements",
                "do_not_bridge_research_outputs_to_execution",
            ],
            safe_to_bundle_now=["manifest_safety_index_refresh", "descriptive_evidence_expansion"],
            must_stay_separate=["parameter_mutation", "learning_to_execution_bridge"],
        ),
        _gate(
            gate_id="gate_4",
            name="environment_hygiene",
            status="pass" if environment_bwrap else "warning",
            evidence={
                "bwrap_on_path": bool(environment_bwrap),
                "bwrap_path": environment_summary.get("bwrap_path"),
                "system_package_mutation_performed": False,
            },
            remaining_work=[] if environment_bwrap else ["operator_may_install_bubblewrap_in_separate_maintenance_task"],
            safe_to_bundle_now=["document_bwrap_warning"],
            must_stay_separate=["sudo", "package_manager_install"],
        ),
        _gate(
            gate_id="gate_5",
            name="future_live_test_design",
            status="blocked_until_exact_ack",
            evidence={
                "live_test_is_this_task": False,
                "exact_operator_ack_present": False,
                "coinbase_poll_authorized": False,
                "state_mutation_authorized": False,
            },
            remaining_work=[
                "future_prompt_must_define_product_side_size_price_logic",
                "future_prompt_must_define_coinbase_read_permission_if_needed",
                "future_prompt_must_define_stop_conditions",
            ],
            ack_required=True,
            safe_to_bundle_now=["preflight_template_only"],
            must_stay_separate=["submit", "cancel", "replace", "reprice", "lifecycle_apply"],
        ),
    ]


def _workstreams(environment_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    bwrap_ok = bool(environment_summary.get("bwrap_on_path"))
    return [
        _workstream(
            key="A_live_lifecycle_safety",
            status="parked_locally",
            remaining_tasks=["keep_gate_0_checks_as_preflight_requirements"],
            blockers=["exact_ack_required_for_any_live_or_lifecycle_action"],
            safe_to_bundle_tasks=["local_status_report", "readiness_gate_report"],
            must_stay_separate_tasks=["coinbase_poll", "new_order", "cancel_replace", "lifecycle_apply"],
            tests_checks=["show_open_orders", "function_preservation_audit", "show_phase_d3_controlled_live_exits"],
            deliverables=["readiness_gate_0_summary"],
            ack_required=False,
        ),
        _workstream(
            key="B_local_state_hygiene",
            status="understood_with_known_stale_field",
            remaining_tasks=["post_filled_stale_field_cleanup_preview_design", "fee_gap_evidence_tracking"],
            blockers=["repair_apply_requires_exact_ack"],
            safe_to_bundle_tasks=["preview_design", "consumer_risk_review"],
            must_stay_separate_tasks=["state_repair_apply", "dust_trade", "manual_close"],
            tests_checks=["state_hash_before_after", "derived_reservation_governance"],
            deliverables=["cleanup_preview_design_doc"],
            ack_required=False,
        ),
        _workstream(
            key="C_d3_d4_execution_readiness",
            status="needs_final_preflight_regression_before_live_test",
            remaining_tasks=["run_exit_lifecycle_apply_path_tests", "run_no_oversell_duplicate_tests"],
            blockers=["future_live_test_details_not_acknowledged"],
            safe_to_bundle_tasks=["regression_summary_report"],
            must_stay_separate_tasks=["reprice", "submit", "cancel", "replace"],
            tests_checks=["D3_D4_safety_regression", "reservation_governance_tests"],
            deliverables=["preflight_regression_result"],
            ack_required=False,
        ),
        _workstream(
            key="D_d5_d6_evidence_learning",
            status="report_only_governed",
            remaining_tasks=["enrich_descriptive_fee_no_fill_cancel_replace_counts"],
            blockers=["no_learning_to_execution_boundary"],
            safe_to_bundle_tasks=["descriptive_evidence_summary", "human_review_export"],
            must_stay_separate_tasks=["parameter_search", "parameter_mutation"],
            tests_checks=["D6_governance_tests", "research_safety_validator"],
            deliverables=["evidence_summary_report"],
            ack_required=False,
        ),
        _workstream(
            key="E_research_report_governance",
            status="available_and_validated",
            remaining_tasks=["make_readiness_report_repeatable"],
            blockers=[],
            safe_to_bundle_tasks=["writer_manifest_safety_index_pipeline"],
            must_stay_separate_tasks=["runtime_strategy_changes"],
            tests_checks=["manifest", "lineage", "safety_validator", "index_export"],
            deliverables=["reports_d6_readiness_bundle"],
            ack_required=False,
        ),
        _workstream(
            key="F_regression_readiness_harness",
            status="partial",
            remaining_tasks=["consolidate_readiness_checks_into_report_only_command"],
            blockers=[],
            safe_to_bundle_tasks=["readiness_report_cli", "focused_tests"],
            must_stay_separate_tasks=["service_restart"],
            tests_checks=["py_compile", "pytest", "local_cli_smoke"],
            deliverables=["build_phase_d6_live_test_readiness_report_cli"],
            ack_required=False,
        ),
        _workstream(
            key="G_environment_hygiene",
            status="ok_with_warning" if not bwrap_ok else "ok",
            remaining_tasks=[] if bwrap_ok else ["install_bubblewrap_later_with_operator_maintenance_ack"],
            blockers=[],
            safe_to_bundle_tasks=["non_mutating_bwrap_detection"],
            must_stay_separate_tasks=["sudo", "apt_install"],
            tests_checks=["command_v_bwrap", "which_bwrap"],
            deliverables=["environment_hygiene_summary"],
            ack_required=False,
        ),
        _workstream(
            key="H_documentation_operator_workflow",
            status="needs_live_test_readiness_template",
            remaining_tasks=["future_live_test_preflight_template", "roadmap_gate_update"],
            blockers=[],
            safe_to_bundle_tasks=["docs_update", "checkpoint_update"],
            must_stay_separate_tasks=["operator_acceptance_of_live_test"],
            tests_checks=["doc_prohibited_phrase_scan"],
            deliverables=["future_preflight_template_doc", "roadmap_update"],
            ack_required=False,
        ),
        _workstream(
            key="I_future_controlled_live_test",
            status="not_authorized",
            remaining_tasks=["define_exact_future_test_prompt", "collect_explicit_acks"],
            blockers=["live_action_not_authorized", "coinbase_poll_not_authorized"],
            safe_to_bundle_tasks=["template_only"],
            must_stay_separate_tasks=["live_order_lifecycle", "coinbase_poll", "state_apply"],
            tests_checks=["all_gates_before_future_prompt"],
            deliverables=["future_ack_matrix"],
            ack_required=True,
        ),
    ]


def _route_scores() -> List[Dict[str, Any]]:
    return [
        _route_score(
            route="A_roadmap_and_readiness_gates_only",
            value_toward_live_test_readiness=6,
            safety_risk=1,
            testability=5,
            size=2,
            bundling_strength=3,
            loop_reduction_value=4,
            touches_trading_state=False,
            ack_required=False,
            decision="defer_because_it_is_less_progress_than_report_harness",
        ),
        _route_score(
            route="B_safe_regression_readiness_report_v1",
            value_toward_live_test_readiness=8,
            safety_risk=2,
            testability=8,
            size=5,
            bundling_strength=6,
            loop_reduction_value=8,
            touches_trading_state=False,
            ack_required=False,
            decision="good_fallback_if_combined_route_grows_too_large",
        ),
        _route_score(
            route="C_historical_evidence_expansion_v1",
            value_toward_live_test_readiness=7,
            safety_risk=2,
            testability=7,
            size=5,
            bundling_strength=5,
            loop_reduction_value=6,
            touches_trading_state=False,
            ack_required=False,
            decision="use_as_component_not_standalone",
        ),
        _route_score(
            route="D_future_live_test_preflight_template_v1",
            value_toward_live_test_readiness=7,
            safety_risk=1,
            testability=4,
            size=3,
            bundling_strength=4,
            loop_reduction_value=7,
            touches_trading_state=False,
            ack_required=False,
            decision="use_as_component_not_standalone",
        ),
        _route_score(
            route="E_local_hygiene_preview_design_v1",
            value_toward_live_test_readiness=6,
            safety_risk=2,
            testability=6,
            size=4,
            bundling_strength=4,
            loop_reduction_value=5,
            touches_trading_state=False,
            ack_required=False,
            decision="defer_until_after_readiness_harness_unless_state_hygiene_blocks",
        ),
        _route_score(
            route="F_combined_readiness_harness_preflight_evidence",
            value_toward_live_test_readiness=9,
            safety_risk=2,
            testability=8,
            size=7,
            bundling_strength=9,
            loop_reduction_value=9,
            touches_trading_state=False,
            ack_required=False,
            decision="chosen_report_only_and_high_value",
        ),
    ]


def _overall_status(gates: List[Dict[str, Any]]) -> str:
    if any(gate["status"] == "blocked" for gate in gates):
        return "blocked_local_safety_issue"
    if any(gate["status"] == "blocked_until_exact_ack" for gate in gates):
        return "readiness_plan_ready_future_live_test_requires_exact_ack"
    if any(gate["status"] == "warning" for gate in gates):
        return "readiness_plan_ready_with_warnings"
    return "readiness_plan_ready"


def build_phase_d6_live_test_readiness_report(
    *,
    open_orders_report: Dict[str, Any],
    function_audit_text: str,
    d3_controlled_exits_report: Dict[str, Any],
    state_hashes_before: Dict[str, str],
    state_hashes_after: Optional[Dict[str, str]] = None,
    governance_bundle_report: Optional[Dict[str, Any]] = None,
    environment_summary: Optional[Dict[str, Any]] = None,
    regression_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    open_summary = _open_orders_summary(open_orders_report)
    audit_summary = parse_function_preservation_audit(function_audit_text)
    d3 = _d3_summary(d3_controlled_exits_report)
    governance_bundle = _normalize_governance_bundle(governance_bundle_report)
    hashes_before = _state_hash_summary(state_hashes_before)
    hashes_after = _state_hash_summary(state_hashes_after or state_hashes_before)
    state_hashes_match = hashes_before == hashes_after
    env = dict(environment_summary or {})
    gates = _readiness_gates(
        open_orders=open_summary,
        function_audit=audit_summary,
        d3=d3,
        state_hashes_match=state_hashes_match,
        governance_bundle=governance_bundle,
        environment_summary=env,
        regression_summary=dict(regression_summary or {}),
    )
    return {
        "generated_at": now_iso(),
        "phase": D6_LIVE_TEST_READINESS_PHASE,
        "status": "d6_live_test_readiness_report_ready",
        "overall_status": _overall_status(gates),
        "scope": {
            "report_only": True,
            "local_checks_only": True,
            "coinbase_interaction": False,
            "trading_state_mutation": False,
            "system_mutation": False,
            "live_test_execution": False,
        },
        "current_state": {
            "open_orders": open_summary,
            "function_preservation_audit": audit_summary,
            "d3_controlled_exits": d3,
            "state_hashes_before": hashes_before,
            "state_hashes_after": hashes_after,
            "state_hashes_match": state_hashes_match,
            "governance_bundle_overall_status": governance_bundle.get("overall_status"),
            "readiness_regression_summary": dict(regression_summary or {}),
        },
        "readiness_workstreams": _workstreams(env),
        "readiness_gates": gates,
        "route_scores": _route_scores(),
        "chosen_route": {
            "route": "F_combined_readiness_harness_preflight_evidence",
            "rationale": "largest safe bundle: reusable readiness report, future preflight template, and D.5/D.6 evidence summary without live or trading-state boundaries",
            "executed_now": True,
        },
        "future_ack_matrix": [
            "coinbase_read_only_poll_ack_if_future_prompt_needs_exchange_evidence",
            "live_order_submit_ack",
            "cancel_replace_reprice_ack",
            "lifecycle_apply_ack",
            "local_repair_apply_ack",
            "config_or_parameter_mutation_ack",
            "system_package_maintenance_ack",
        ],
        "stop_conditions": [
            "stop_before_coinbase_poll",
            "stop_before_live_order_action",
            "stop_before_lifecycle_apply",
            "stop_before_local_repair_apply",
            "stop_before_config_or_parameter_mutation",
            "stop_before_system_package_mutation",
        ],
        "warnings": [
            "future_live_test_not_authorized",
            "bwrap_missing_if_not_on_path",
            "stale_denormalized_reserved_field_known",
            "tp_close_fee_gap_known",
            "report_only_no_execution_bridge",
        ],
        "blockers": [
            gate["gate_id"]
            for gate in gates
            if gate["status"] in {"blocked", "blocked_until_exact_ack"}
        ],
        **_safety_flags(),
    }


__all__ = [
    "D6_LIVE_TEST_READINESS_PHASE",
    "build_phase_d6_live_test_readiness_report",
]
