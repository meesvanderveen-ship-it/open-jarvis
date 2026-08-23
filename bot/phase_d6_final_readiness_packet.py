from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_FINAL_READINESS_PACKET_PHASE = "D6_final_readiness_packet_v1"


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


def _content(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not report:
        return {}
    if isinstance(report.get("content"), dict):
        return dict(report["content"])
    return dict(report)


def _gate_summary(readiness: Dict[str, Any]) -> Dict[str, Any]:
    rows = {}
    for gate in readiness.get("readiness_gates") or []:
        if isinstance(gate, dict) and gate.get("gate_id"):
            rows[str(gate["gate_id"])] = {
                "name": gate.get("name"),
                "status": gate.get("status"),
                "ack_required": bool(gate.get("ack_required")),
                "remaining_work": list(gate.get("remaining_work") or []),
                "must_stay_separate": list(gate.get("must_stay_separate") or []),
                "evidence": dict(gate.get("evidence") or {}),
            }
    return rows


def _route_scores() -> List[Dict[str, Any]]:
    return [
        {
            "route": "A_final_readiness_packet_consolidation",
            "value_toward_future_live_test_review": 8,
            "risk": 1,
            "testability": 8,
            "implementation_size": 4,
            "bundling_strength": 7,
            "loop_reduction": 8,
            "state_impact": "none",
            "ack_required": False,
            "decision": "included",
        },
        {
            "route": "B_safe_regression_harness_consolidation",
            "value_toward_future_live_test_review": 8,
            "risk": 2,
            "testability": 9,
            "implementation_size": 6,
            "bundling_strength": 8,
            "loop_reduction": 9,
            "state_impact": "none",
            "ack_required": False,
            "decision": "included_as_reported_regression_evidence_not_new_runner",
        },
        {
            "route": "C_post_filled_stale_field_cleanup_design",
            "value_toward_future_live_test_review": 6,
            "risk": 2,
            "testability": 7,
            "implementation_size": 5,
            "bundling_strength": 5,
            "loop_reduction": 5,
            "state_impact": "none_if_preview_only",
            "ack_required": False,
            "decision": "deferred_not_blocking_future_prompt_review",
        },
        {
            "route": "D_live_test_preflight_prompt_skeleton",
            "value_toward_future_live_test_review": 8,
            "risk": 1,
            "testability": 5,
            "implementation_size": 3,
            "bundling_strength": 6,
            "loop_reduction": 8,
            "state_impact": "none",
            "ack_required": False,
            "decision": "included_as_template_only",
        },
        {
            "route": "E_d5_d6_evidence_detail_expansion",
            "value_toward_future_live_test_review": 7,
            "risk": 2,
            "testability": 7,
            "implementation_size": 6,
            "bundling_strength": 6,
            "loop_reduction": 6,
            "state_impact": "none",
            "ack_required": False,
            "decision": "deferred_evidence_summary_already_available",
        },
        {
            "route": "F_combined_final_packet_regression_preflight",
            "value_toward_future_live_test_review": 10,
            "risk": 2,
            "testability": 8,
            "implementation_size": 7,
            "bundling_strength": 10,
            "loop_reduction": 10,
            "state_impact": "none",
            "ack_required": False,
            "decision": "chosen",
        },
    ]


def _blocker_map(gates: Dict[str, Any]) -> Dict[str, Any]:
    gate_1 = gates.get("gate_1") or {}
    gate_4 = gates.get("gate_4") or {}
    gate_5 = gates.get("gate_5") or {}
    return {
        "must_finish_before_future_live_test_prompt": [
            "current_local_safety_refresh",
            "selected_d3_d4_d6_readiness_regression",
            "d6_report_safety_validation",
            "explicit_future_prompt_fields",
        ],
        "nice_to_have_before_future_live_test_prompt": [
            "post_filled_stale_field_cleanup_preview_design",
            "richer_fee_no_fill_cancel_replace_evidence_summary",
            "bubblewrap_install_in_separate_maintenance_task",
        ],
        "must_remain_separate_ack_gated": [
            "coinbase_read_only_poll",
            "submit",
            "cancel_replace_reprice",
            "lifecycle_apply",
            "local_repair_apply",
            "dust_or_manual_close",
            "service_or_config_mutation",
            "parameter_mutation_or_approval",
            "learning_to_execution",
            "system_package_mutation",
        ],
        "can_be_deferred": [
            "state_denormalized_field_repair_apply",
            "tp_close_fee_field_repair_apply",
            "bubblewrap_os_install",
            "additional_historical_evidence_expansion",
        ],
        "warning_disposition": {
            "gate_1_state_hygiene": {
                "status": gate_1.get("status"),
                "does_block_future_prompt_review": False,
                "reason": "derived reservation governance is zero, local open orders are zero, and repair apply remains separately gated",
            },
            "gate_4_environment_hygiene": {
                "status": gate_4.get("status"),
                "does_block_future_prompt_review": False,
                "reason": "bwrap absence is an operator environment maintenance warning and no system mutation is authorized here",
            },
            "gate_5_future_live_test_design": {
                "status": gate_5.get("status"),
                "does_block_live_action": True,
                "reason": "future live action requires an exact separate ACK",
            },
        },
    }


def build_phase_d6_final_readiness_packet(
    *,
    readiness_report: Dict[str, Any],
    governance_evidence_report: Optional[Dict[str, Any]] = None,
    readiness_index_report: Optional[Dict[str, Any]] = None,
    regression_summary: Optional[Dict[str, Any]] = None,
    state_hashes_before: Optional[Dict[str, str]] = None,
    state_hashes_after: Optional[Dict[str, str]] = None,
    environment_summary: Optional[Dict[str, Any]] = None,
    source_report_paths: Iterable[str] = (),
) -> Dict[str, Any]:
    readiness = _content(readiness_report)
    governance = _content(governance_evidence_report)
    index = _content(readiness_index_report)
    gates = _gate_summary(readiness)
    gate_status_counts: Dict[str, int] = {}
    for gate in gates.values():
        status = str(gate.get("status") or "unknown")
        gate_status_counts[status] = gate_status_counts.get(status, 0) + 1
    hashes_before = dict(state_hashes_before or {})
    hashes_after = dict(state_hashes_after or state_hashes_before or {})
    gate5_blocked = (gates.get("gate_5") or {}).get("status") == "blocked_until_exact_ack"
    local_safety_ok = (
        (gates.get("gate_0") or {}).get("status") == "pass"
        and readiness.get("current_state", {}).get("state_hashes_match") is True
    )
    regression_ok = (gates.get("gate_2") or {}).get("status") == "pass"
    report_governance_ok = (gates.get("gate_3") or {}).get("status") == "pass"
    final_status = (
        "ready_for_future_prompt_review_ack_required"
        if local_safety_ok and regression_ok and report_governance_ok and gate5_blocked
        else "not_ready_for_future_prompt_review"
    )
    return {
        "generated_at": now_iso(),
        "phase": D6_FINAL_READINESS_PACKET_PHASE,
        "status": "d6_final_readiness_packet_ready",
        "final_status": final_status,
        "scope": {
            "report_only": True,
            "local_checks_only": True,
            "coinbase_interaction": False,
            "openai_api_interaction": False,
            "trading_state_mutation": False,
            "system_mutation": False,
            "live_test_execution": False,
        },
        "chosen_route": {
            "route": "F_combined_final_packet_regression_preflight",
            "rationale": "consolidates the latest local safety state, readiness gates, regression evidence, D.6 reports, and future ACK matrix without live or state boundaries",
        },
        "route_scores": _route_scores(),
        "readiness_gate_summary": {
            "gate_status_counts": dict(sorted(gate_status_counts.items())),
            "gates": gates,
        },
        "remaining_readiness_work": _blocker_map(gates),
        "regression_summary": dict(regression_summary or readiness.get("current_state", {}).get("readiness_regression_summary") or {}),
        "report_inputs": {
            "source_report_paths": sorted(str(path) for path in source_report_paths),
            "governance_evidence_overall_status": governance.get("overall_status"),
            "governance_evidence_row_count": (governance.get("historical_evidence_summary") or {}).get("evidence_row_count"),
            "readiness_report_overall_status": readiness.get("overall_status"),
            "readiness_index_status": index.get("status"),
            "readiness_index_safety_status": (index.get("safety_validation_summary") or {}).get("overall_status"),
        },
        "state_hashes": {
            "before": hashes_before,
            "after": hashes_after,
            "match": hashes_before == hashes_after,
        },
        "environment_summary": dict(environment_summary or {}),
        "future_prompt_packet": {
            "future_prompt_template": "docs/FUTURE_LIVE_TEST_PROMPT_SKELETON.md",
            "preflight_template": "docs/FUTURE_LIVE_TEST_PREFLIGHT_TEMPLATE.md",
            "required_operator_decisions": [
                "whether_to_allow_coinbase_read_only_poll",
                "whether_to_allow_submit",
                "whether_to_allow_cancel_replace_or_reprice",
                "whether_to_allow_lifecycle_apply_after_terminal_evidence",
                "whether_to_accept_bwrap_warning_or_handle_it_separately",
                "whether_to_defer_stale_field_repair",
            ],
        },
        "warnings": [
            "final_readiness_packet_report_only",
            "future_live_test_requires_exact_ack",
            "stale_denormalized_reserved_field_remains_warning",
            "tp_close_fee_gap_remains_warning",
            "bwrap_missing_if_not_on_path",
            "no_live_actions_approved",
            "no_state_repairs_approved",
        ],
        "blockers": ["future_live_test_exact_ack_missing"] if gate5_blocked else [],
        **_safety_flags(),
    }


__all__ = [
    "D6_FINAL_READINESS_PACKET_PHASE",
    "build_phase_d6_final_readiness_packet",
]
